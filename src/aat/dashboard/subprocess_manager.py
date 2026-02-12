"""Subprocess manager for running AAT CLI commands from the dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections import deque
from enum import StrEnum


class ProcessStatus(StrEnum):
    """Subprocess status."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


class SubprocessManager:
    """Manages a single AAT CLI subprocess.

    Captures stdout/stderr into a bounded deque for log streaming.
    Only one process can run at a time.
    """

    def __init__(self, max_log_lines: int = 2000) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._status = ProcessStatus.IDLE
        self._return_code: int | None = None
        self._log: deque[str] = deque(maxlen=max_log_lines)
        self._read_task: asyncio.Task[None] | None = None

    @property
    def status(self) -> ProcessStatus:
        return self._status

    @property
    def return_code(self) -> int | None:
        return self._return_code

    @property
    def log_lines(self) -> list[str]:
        return list(self._log)

    @property
    def is_running(self) -> bool:
        return self._status == ProcessStatus.RUNNING

    async def start(self, args: list[str]) -> None:
        """Start an AAT CLI subprocess.

        Args:
            args: CLI arguments, e.g. ["run", "scenarios/"].
        """
        if self.is_running:
            msg = "A process is already running"
            raise RuntimeError(msg)

        self._log.clear()
        self._return_code = None
        self._status = ProcessStatus.RUNNING

        cmd = [sys.executable, "-m", "aat.cli.main", *args]
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._read_task = asyncio.create_task(self._read_output())

    async def stop(self) -> None:
        """Terminate the running subprocess."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
        self._status = ProcessStatus.IDLE

    async def wait(self) -> int:
        """Wait for subprocess to finish and return exit code."""
        if self._read_task:
            await self._read_task
        if self._process:
            await self._process.wait()
            self._return_code = self._process.returncode
        return self._return_code or 0

    async def _read_output(self) -> None:
        """Read subprocess stdout line by line into the log deque."""
        assert self._process is not None
        assert self._process.stdout is not None
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                self._log.append(decoded)
        finally:
            if self._process.returncode is None:
                await self._process.wait()
            self._return_code = self._process.returncode
            self._status = (
                ProcessStatus.FINISHED
                if self._return_code == 0
                else ProcessStatus.ERROR
            )
