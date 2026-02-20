"""Asyncio background worker — polls DB for queued tests and executes them.

Single-process, no Celery. Tracks asyncio.Task references for proper cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.database import async_session
from app.executor import execute_test, generate_scenarios_for_test
from app.middleware import get_concurrent_limit
from app.models import Test, TestStatus, User, UserTier
from app.ws import ws_manager

logger = logging.getLogger(__name__)


class Worker:
    """Background worker that polls DB and executes queued tests."""

    def __init__(self) -> None:
        self._running = False
        self._active: int = 0
        self._task: asyncio.Task[None] | None = None
        self._tasks: dict[int, asyncio.Task[None]] = {}  # test_id → asyncio.Task

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
            "Worker started (max_concurrent=%d, poll_interval=%.1fs, stuck_timeout=%dm)",
            settings.max_concurrent,
            settings.worker_poll_interval,
            settings.stuck_timeout_minutes,
        )

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        # Cancel all active tasks
        for tid, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                logger.info("Cancelled active task for test %d on shutdown", tid)
        logger.info("Worker stopped (active=%d)", self._active)

    async def _poll_loop(self) -> None:
        """Main loop: recover stuck tests, then poll for queued tests."""
        await self._recover_stuck()

        poll_count = 0
        # Check stuck tests every ~20 seconds
        stuck_check_interval = max(1, int(20 / settings.worker_poll_interval))

        while self._running:
            try:
                # Periodically clean up stuck tests and sync active counter
                poll_count += 1
                if poll_count % stuck_check_interval == 0:
                    await self._fail_stuck_tests()
                    self._sync_active_counter()

                # Only claim a test if we have a free slot
                if self._active < settings.max_concurrent:
                    claimed = await self._claim_next()
                    if claimed is not None:
                        test_id, original_status = claimed
                        self._active += 1
                        task = asyncio.create_task(self._run(test_id, original_status))
                        self._tasks[test_id] = task
                        continue  # Check for more immediately
            except Exception:
                logger.exception("Worker poll error")

            await asyncio.sleep(settings.worker_poll_interval)

    def _sync_active_counter(self) -> None:
        """Sync _active counter with actual running tasks (safety net)."""
        # Clean up finished tasks
        done_ids = [tid for tid, t in self._tasks.items() if t.done()]
        for tid in done_ids:
            self._tasks.pop(tid, None)

        actual = len(self._tasks)
        if self._active != actual:
            logger.warning(
                "Active counter out of sync: counter=%d, actual_tasks=%d. Correcting.",
                self._active, actual,
            )
            self._active = actual

    async def _recover_stuck(self) -> None:
        """On startup: fail tests stuck in RUNNING from previous crash."""
        async with async_session() as db:
            result = await db.execute(
                select(Test).where(Test.status == TestStatus.RUNNING)
            )
            stuck = list(result.scalars().all())
            for test in stuck:
                test.status = TestStatus.FAILED
                test.error_message = "Test was interrupted by server restart"
                test.updated_at = datetime.now(UTC)
                logger.warning("Startup: marked stuck test %d as FAILED", test.id)
            if stuck:
                await db.commit()

    async def _fail_stuck_tests(self) -> None:
        """Periodically fail tests stuck in RUNNING or QUEUED beyond the timeout."""
        cutoff = datetime.now(UTC) - timedelta(
            minutes=settings.stuck_timeout_minutes
        )
        async with async_session() as db:
            result = await db.execute(
                select(Test).where(
                    Test.status.in_([TestStatus.RUNNING, TestStatus.QUEUED]),
                    Test.updated_at < cutoff,
                )
            )
            stuck = list(result.scalars().all())
            for test in stuck:
                old_status = test.status
                test.status = TestStatus.FAILED
                test.error_message = (
                    f"Test timed out ({old_status.value} > {settings.stuck_timeout_minutes} min)"
                )
                test.updated_at = datetime.now(UTC)
                logger.warning(
                    "Auto-failed stuck test %d (%s > %d min)",
                    test.id,
                    old_status.value,
                    settings.stuck_timeout_minutes,
                )

                # Cancel the asyncio task if it exists (for RUNNING tests)
                task = self._tasks.pop(test.id, None)
                if task and not task.done():
                    task.cancel()
                    logger.info("Cancelled stuck asyncio task for test %d", test.id)

                await ws_manager.broadcast(
                    test.id,
                    {
                        "type": "test_fail",
                        "test_id": test.id,
                        "error": test.error_message,
                    },
                )
            if stuck:
                await db.commit()

    async def _claim_next(self) -> tuple[int, TestStatus] | None:
        """Claim the next eligible test respecting per-user concurrency limits.

        Returns (test_id, original_status) or None.
        GENERATING has priority over QUEUED.
        A user's test is skipped if they've reached their tier's concurrent limit,
        allowing other users' tests to proceed independently.
        """
        _is_sqlite = settings.database_url.startswith("sqlite")

        async with async_session() as db:
            # 1. Per-user RUNNING counts (single query)
            running_q = (
                select(Test.user_id, func.count())
                .where(Test.status == TestStatus.RUNNING)
                .group_by(Test.user_id)
            )
            running_result = await db.execute(running_q)
            user_running: dict[str, int] = dict(running_result.all())

            # 2. Candidate tests (up to 20)
            stmt = (
                select(Test)
                .where(Test.status.in_([TestStatus.GENERATING, TestStatus.QUEUED]))
                .order_by(
                    # GENERATING first, then QUEUED
                    (Test.status == TestStatus.QUEUED).asc(),
                    Test.created_at.asc(),
                )
                .limit(20)
            )
            if not _is_sqlite:
                stmt = stmt.with_for_update(skip_locked=True)

            result = await db.execute(stmt)
            candidates = list(result.scalars().all())
            if not candidates:
                return None

            # 3. Fetch tiers for candidate users
            candidate_user_ids = {t.user_id for t in candidates}
            tier_result = await db.execute(
                select(User.id, User.tier).where(User.id.in_(candidate_user_ids))
            )
            user_tiers: dict[str, UserTier] = dict(tier_result.all())

            # 4. First eligible candidate (per-user limit not reached)
            for test in candidates:
                tier = user_tiers.get(test.user_id, UserTier.FREE)
                tier_limit = get_concurrent_limit(tier)
                running_count = user_running.get(test.user_id, 0)
                if running_count >= tier_limit:
                    continue  # This user is at capacity, try next

                # Claim this test
                original_status = test.status
                test.status = TestStatus.RUNNING
                test.updated_at = datetime.now(UTC)
                await db.commit()
                logger.info(
                    "Claimed test %d (%s) for user %s (%d/%d running)",
                    test.id, original_status.value, test.user_id,
                    running_count + 1, tier_limit,
                )
                return test.id, original_status

            return None

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
        except asyncio.CancelledError:
            logger.warning("Test %d was cancelled", test_id)
            # DB status already updated by _fail_stuck_tests; just clean up
        except Exception as exc:
            logger.exception("Test %d failed unexpectedly", test_id)
            async with async_session() as db:
                test = (
                    await db.execute(select(Test).where(Test.id == test_id))
                ).scalar_one_or_none()
                if test and test.status == TestStatus.RUNNING:
                    test.status = TestStatus.FAILED
                    test.result_json = json.dumps({"error": str(exc)})
                    test.error_message = str(exc)
                    test.updated_at = datetime.now(UTC)
                    await db.commit()

            await ws_manager.broadcast(
                test_id,
                {"type": "test_fail", "test_id": test_id, "error": str(exc)},
            )
        finally:
            self._active = max(0, self._active - 1)
            self._tasks.pop(test_id, None)

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
            test.updated_at = datetime.now(UTC)
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
            test.updated_at = datetime.now(UTC)
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
