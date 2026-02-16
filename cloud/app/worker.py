"""Asyncio background worker — polls DB for queued tests and executes them.

Single-process, no Celery. Uses asyncio.Semaphore for concurrency control.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.executor import execute_test, generate_scenarios_for_test
from app.models import Test, TestStatus
from app.ws import ws_manager

logger = logging.getLogger(__name__)


class Worker:
    """Background worker that polls DB and executes queued tests."""

    def __init__(self) -> None:
        self._running = False
        self._active: int = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_count(self) -> int:
        return self._active

    async def start(self) -> None:
        """Start the background poll loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Worker started (max_concurrent=%d, poll_interval=%.1fs)",
            settings.max_concurrent,
            settings.worker_poll_interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Worker stopped (active=%d)", self._active)

    async def _poll_loop(self) -> None:
        """Main loop: recover stuck tests, then poll for queued tests."""
        await self._recover_stuck()

        while self._running:
            try:
                # Only claim a test if we have a free slot
                if self._active < settings.max_concurrent:
                    claimed = await self._claim_next()
                    if claimed is not None:
                        test_id, original_status = claimed
                        self._active += 1
                        asyncio.create_task(self._run(test_id, original_status))
                        continue  # Check for more immediately
            except Exception:
                logger.exception("Worker poll error")

            await asyncio.sleep(settings.worker_poll_interval)

    async def _recover_stuck(self) -> None:
        """Reset any RUNNING tests back to appropriate state (from previous crash)."""
        async with async_session() as db:
            result = await db.execute(
                select(Test).where(Test.status == TestStatus.RUNNING)
            )
            stuck = list(result.scalars().all())
            for test in stuck:
                # If scenario_yaml exists, it was mid-execution → QUEUED
                # If not, it was mid-generation → GENERATING
                if test.scenario_yaml:
                    test.status = TestStatus.QUEUED
                    logger.warning("Recovered stuck test %d → QUEUED", test.id)
                else:
                    test.status = TestStatus.GENERATING
                    logger.warning("Recovered stuck test %d → GENERATING", test.id)
            if stuck:
                await db.commit()

    async def _claim_next(self) -> tuple[int, TestStatus] | None:
        """Atomically claim the next GENERATING or QUEUED test.

        Returns (test_id, original_status) or None.
        GENERATING has priority over QUEUED.
        """
        _is_sqlite = settings.database_url.startswith("sqlite")

        async with async_session() as db:
            stmt = (
                select(Test)
                .where(Test.status.in_([TestStatus.GENERATING, TestStatus.QUEUED]))
                .order_by(
                    # GENERATING first, then QUEUED
                    (Test.status == TestStatus.QUEUED).asc(),
                    Test.created_at.asc(),
                )
                .limit(1)
            )
            if not _is_sqlite:
                stmt = stmt.with_for_update(skip_locked=True)

            result = await db.execute(stmt)
            test = result.scalar_one_or_none()
            if test is None:
                return None

            original_status = test.status
            test.status = TestStatus.RUNNING
            test.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Claimed test %d (%s) for processing", test.id, original_status.value)
            return test.id, original_status

    async def _run(self, test_id: int, original_status: TestStatus) -> None:
        """Process a test based on its original status.

        GENERATING → generate scenarios → REVIEW (wait for user)
        QUEUED → execute test → DONE/FAILED
        """
        try:
            if original_status == TestStatus.GENERATING:
                await self._run_generate(test_id)
            else:
                await self._run_execute(test_id)
        except Exception as exc:
            logger.exception("Test %d failed unexpectedly", test_id)
            async with async_session() as db:
                test = (
                    await db.execute(select(Test).where(Test.id == test_id))
                ).scalar_one_or_none()
                if test:
                    test.status = TestStatus.FAILED
                    test.result_json = json.dumps({"error": str(exc)})
                    test.error_message = str(exc)
                    test.updated_at = datetime.now(timezone.utc)
                    await db.commit()

            await ws_manager.broadcast(
                test_id,
                {"type": "test_fail", "test_id": test_id, "error": str(exc)},
            )
        finally:
            self._active -= 1

    async def _run_generate(self, test_id: int) -> None:
        """Generate scenarios and transition to REVIEW."""
        await ws_manager.broadcast(
            test_id, {"type": "test_start", "test_id": test_id, "phase": "generate"}
        )

        result = await generate_scenarios_for_test(test_id, ws_manager)

        async with async_session() as db:
            test = (
                await db.execute(select(Test).where(Test.id == test_id))
            ).scalar_one()
            if result.get("error"):
                test.status = TestStatus.FAILED
                test.error_message = result["error"]
            else:
                test.status = TestStatus.REVIEW
            test.updated_at = datetime.now(timezone.utc)
            await db.commit()

        if result.get("error"):
            await ws_manager.broadcast(
                test_id,
                {"type": "test_fail", "test_id": test_id, "error": result["error"]},
            )
        else:
            logger.info("Test %d scenarios generated → REVIEW", test_id)

    async def _run_execute(self, test_id: int) -> None:
        """Execute test scenarios and transition to DONE/FAILED."""
        await ws_manager.broadcast(
            test_id, {"type": "test_start", "test_id": test_id}
        )

        result = await execute_test(test_id, ws_manager)

        async with async_session() as db:
            test = (
                await db.execute(select(Test).where(Test.id == test_id))
            ).scalar_one()
            test.status = (
                TestStatus.DONE if result.get("passed") else TestStatus.FAILED
            )
            test.result_json = json.dumps(result, default=str)
            if result.get("error"):
                test.error_message = result["error"]
            test.updated_at = datetime.now(timezone.utc)
            await db.commit()

        await ws_manager.broadcast(
            test_id,
            {
                "type": "test_complete",
                "test_id": test_id,
                "passed": result.get("passed", False),
            },
        )
        logger.info(
            "Test %d completed (passed=%s, %.0fms)",
            test_id,
            result.get("passed"),
            result.get("duration_ms", 0),
        )


worker = Worker()
