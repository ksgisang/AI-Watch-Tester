"""Tests for SubprocessManager."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from aat.dashboard.subprocess_manager import ProcessStatus, SubprocessManager


class TestSubprocessManager:
    """SubprocessManager test suite."""

    def test_initial_state(self) -> None:
        mgr = SubprocessManager()
        assert mgr.status == ProcessStatus.IDLE
        assert mgr.return_code is None
        assert mgr.log_lines == []
        assert not mgr.is_running

    async def test_start_and_wait(self) -> None:
        mgr = SubprocessManager()
        await mgr.start(["-c", "import sys; sys.exit(0)"])
        # Override: use python directly
        await mgr.stop()

    async def test_start_simple_command(self) -> None:
        mgr = SubprocessManager()
        # Directly test with a simple Python command
        mgr._log.clear()
        mgr._return_code = None
        mgr._status = ProcessStatus.RUNNING

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "print('hello')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        mgr._process = proc
        mgr._read_task = asyncio.create_task(mgr._read_output())
        await mgr._read_task
        await proc.wait()

        assert "hello" in mgr.log_lines
        assert mgr.return_code == 0
        assert mgr.status == ProcessStatus.FINISHED

    async def test_stop_terminates_process(self) -> None:
        mgr = SubprocessManager()
        mgr._status = ProcessStatus.RUNNING

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        mgr._process = proc
        mgr._read_task = asyncio.create_task(mgr._read_output())

        await mgr.stop()
        assert mgr.status == ProcessStatus.IDLE

    async def test_error_status_on_nonzero_exit(self) -> None:
        mgr = SubprocessManager()
        mgr._log.clear()
        mgr._return_code = None
        mgr._status = ProcessStatus.RUNNING

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; sys.exit(1)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        mgr._process = proc
        mgr._read_task = asyncio.create_task(mgr._read_output())
        await mgr._read_task
        await proc.wait()

        assert mgr.return_code == 1
        assert mgr.status == ProcessStatus.ERROR

    def test_max_log_lines(self) -> None:
        mgr = SubprocessManager(max_log_lines=5)
        for i in range(10):
            mgr._log.append(f"line {i}")
        assert len(mgr.log_lines) == 5
        assert mgr.log_lines[0] == "line 5"

    async def test_cannot_start_twice(self) -> None:
        mgr = SubprocessManager()
        mgr._status = ProcessStatus.RUNNING
        with pytest.raises(RuntimeError, match="already running"):
            await mgr.start(["--help"])
        mgr._status = ProcessStatus.IDLE

    async def test_start_raw_arbitrary_command(self) -> None:
        mgr = SubprocessManager()
        await mgr.start_raw([sys.executable, "-c", "print('raw_hello')"])
        code = await mgr.wait()
        assert code == 0
        assert "raw_hello" in mgr.log_lines

    async def test_on_line_callback(self) -> None:
        collected: list[str] = []
        mgr = SubprocessManager(on_line=collected.append)
        await mgr.start_raw([sys.executable, "-c", "print('cb_line')"])
        await mgr.wait()
        assert "cb_line" in collected

    async def test_start_raw_with_cwd(self, tmp_path: Path) -> None:
        mgr = SubprocessManager()
        await mgr.start_raw(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=tmp_path,
        )
        await mgr.wait()
        assert str(tmp_path) in mgr.log_lines[0]

    async def test_start_raw_cannot_start_twice(self) -> None:
        mgr = SubprocessManager()
        mgr._status = ProcessStatus.RUNNING
        with pytest.raises(RuntimeError, match="already running"):
            await mgr.start_raw([sys.executable, "-c", "pass"])
        mgr._status = ProcessStatus.IDLE

    def test_pid_property(self) -> None:
        mgr = SubprocessManager()
        assert mgr.pid is None
