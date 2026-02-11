"""Waiter — screen stabilization detection via polling + hash.

Polls screenshots at fixed intervals and compares MD5 hashes.
When N consecutive hashes match, the screen is considered stable.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aat.engine.base import BaseEngine


class Waiter:
    """Screen stabilization detector."""

    def __init__(
        self,
        poll_interval_ms: int = 500,
        stable_count: int = 2,
        max_wait_ms: int = 10000,
    ) -> None:
        self._poll_interval = poll_interval_ms / 1000
        self._stable_count = stable_count
        self._max_wait = max_wait_ms / 1000

    async def wait_until_stable(self, engine: BaseEngine) -> bool:
        """Wait until the screen stabilizes.

        Args:
            engine: BaseEngine instance (uses duck typing to avoid circular import).

        Returns:
            True if stabilized, False if max_wait exceeded.
        """
        start = time.monotonic()
        prev_hash: str | None = None
        consecutive = 0

        while (time.monotonic() - start) < self._max_wait:
            screenshot: bytes = await engine.screenshot()
            current_hash = hashlib.md5(screenshot).hexdigest()  # noqa: S324

            if current_hash == prev_hash:
                consecutive += 1
                if consecutive >= self._stable_count:
                    return True
            else:
                consecutive = 0

            prev_hash = current_hash
            await asyncio.sleep(self._poll_interval)

        # max_wait exceeded — not confirmed stable, but continue
        return False
