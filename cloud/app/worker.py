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
from app.executor import execute_test
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
                    test_id = await self._claim_next()
                    if test_id is not None:
                        self._active += 1
                        asyncio.create_task(self._run(test_id))
                        continue  # Check for more immediately
            except Exception:
                logger.exception("Worker poll error")

            await asyncio.sleep(settings.worker_poll_interval)

    async def _recover_stuck(self) -> None:
        """Reset any RUNNING tests back to QUEUED (from previous crash)."""
        async with async_session() as db:
            result = await db.execute(
                select(Test).where(Test.status == TestStatus.RUNNING)
            )
            stuck = list(result.scalars().all())
            for test in stuck:
                test.status = TestStatus.QUEUED
                logger.warning("Recovered stuck test %d → QUEUED", test.id)
            if stuck:
                await db.commit()

    async def _claim_next(self) -> int | None:
        """Atomically claim the next queued test (mark as RUNNING)."""
        async with async_session() as db:
            result = await db.execute(
                select(Test)
                .where(Test.status == TestStatus.QUEUED)
                .order_by(Test.created_at.asc())
                .limit(1)
            )
            test = result.scalar_one_or_none()
            if test is None:
                return None

            test.status = TestStatus.RUNNING
            test.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Claimed test %d for execution", test.id)
            return test.id

    async def _run(self, test_id: int) -> None:
        """Execute a test and update its DB status."""
        try:
            await ws_manager.broadcast(
                test_id, {"type": "test_start", "test_id": test_id}
            )

            result = await execute_test(test_id, ws_manager)

            # Update DB with results
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


worker = Worker()
