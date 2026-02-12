"""Git operations wrapper using async subprocess."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from aat.core.exceptions import GitOpsError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aat.core.models import FileChange


class GitOps:
    """Async git subprocess wrapper.

    All operations run via ``asyncio.create_subprocess_exec`` — no external
    git library required.
    """

    def __init__(self, work_dir: Path | None = None) -> None:
        self._work_dir = work_dir or Path.cwd()

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    async def _run_git(self, *args: str) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=self._work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode().strip(),
            stderr_bytes.decode().strip(),
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def is_git_repo(self) -> bool:
        """Check if work_dir is inside a git repository."""
        rc, _, _ = await self._run_git("rev-parse", "--is-inside-work-tree")
        return rc == 0

    async def current_branch(self) -> str:
        """Return current branch name."""
        rc, stdout, stderr = await self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            msg = f"Failed to get current branch: {stderr}"
            raise GitOpsError(msg)
        return stdout

    async def has_uncommitted_changes(self) -> bool:
        """Check for uncommitted changes (staged or unstaged)."""
        rc, stdout, _ = await self._run_git("status", "--porcelain")
        if rc != 0:
            return False
        return bool(stdout)

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    async def create_branch(self, name: str) -> None:
        """Create and checkout a new branch."""
        rc, _, stderr = await self._run_git("checkout", "-b", name)
        if rc != 0:
            msg = f"Failed to create branch '{name}': {stderr}"
            raise GitOpsError(msg)

    async def checkout(self, name: str) -> None:
        """Checkout an existing branch."""
        rc, _, stderr = await self._run_git("checkout", name)
        if rc != 0:
            msg = f"Failed to checkout '{name}': {stderr}"
            raise GitOpsError(msg)

    async def delete_branch(self, name: str) -> None:
        """Delete a branch (force)."""
        rc, _, stderr = await self._run_git("branch", "-D", name)
        if rc != 0:
            msg = f"Failed to delete branch '{name}': {stderr}"
            raise GitOpsError(msg)

    # ------------------------------------------------------------------
    # File + commit operations
    # ------------------------------------------------------------------

    async def apply_file_changes(self, changes: list[FileChange]) -> list[Path]:
        """Write file changes to disk. Returns list of modified paths."""
        written: list[Path] = []
        for change in changes:
            file_path = self._work_dir / change.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(change.modified, encoding="utf-8")
            written.append(file_path)
        return written

    async def commit_changes(self, paths: list[Path], message: str) -> str:
        """Stage files and commit. Returns commit hash."""
        str_paths = [str(p) for p in paths]
        rc, _, stderr = await self._run_git("add", *str_paths)
        if rc != 0:
            msg = f"git add failed: {stderr}"
            raise GitOpsError(msg)

        rc, _, stderr = await self._run_git("commit", "-m", message)
        if rc != 0:
            msg = f"git commit failed: {stderr}"
            raise GitOpsError(msg)

        rc, stdout, stderr = await self._run_git("rev-parse", "--short", "HEAD")
        if rc != 0:
            msg = f"Failed to get commit hash: {stderr}"
            raise GitOpsError(msg)
        return stdout

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def on_fix_branch(self, name: str) -> AsyncIterator[None]:  # type: ignore[return-type]
        """Create a fix branch, yield, then checkout back to original branch.

        On exit, always returns to the original branch regardless of success
        or failure.
        """
        original = await self.current_branch()
        await self.create_branch(name)
        try:
            yield
        finally:
            await self.checkout(original)
