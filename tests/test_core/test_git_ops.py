"""Tests for GitOps — async git subprocess wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aat.core.exceptions import GitOpsError
from aat.core.git_ops import GitOps
from aat.core.models import FileChange

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    import asyncio

    async def _run(*args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    await _run("git", "init")
    await _run("git", "config", "user.email", "test@test.com")
    await _run("git", "config", "user.name", "Test")
    # Create initial commit (needed for branching)
    (path / "README.md").write_text("# Test\n")
    await _run("git", "add", "README.md")
    await _run("git", "commit", "-m", "initial")


# ---------------------------------------------------------------------------
# Tests: query helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_git_repo_true(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    assert await ops.is_git_repo() is True


@pytest.mark.asyncio
async def test_is_git_repo_false(tmp_path: Path) -> None:
    ops = GitOps(tmp_path)
    assert await ops.is_git_repo() is False


@pytest.mark.asyncio
async def test_current_branch(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    branch = await ops.current_branch()
    assert branch in ("main", "master")


@pytest.mark.asyncio
async def test_has_uncommitted_changes_clean(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    assert await ops.has_uncommitted_changes() is False


@pytest.mark.asyncio
async def test_has_uncommitted_changes_dirty(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    (tmp_path / "dirty.txt").write_text("dirty")
    ops = GitOps(tmp_path)
    assert await ops.has_uncommitted_changes() is True


# ---------------------------------------------------------------------------
# Tests: branch operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_branch(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    await ops.create_branch("aat/fix-001")
    assert await ops.current_branch() == "aat/fix-001"


@pytest.mark.asyncio
async def test_checkout(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    original = await ops.current_branch()
    await ops.create_branch("aat/fix-002")
    await ops.checkout(original)
    assert await ops.current_branch() == original


@pytest.mark.asyncio
async def test_delete_branch(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    original = await ops.current_branch()
    await ops.create_branch("aat/fix-003")
    await ops.checkout(original)
    await ops.delete_branch("aat/fix-003")
    # Verify branch is gone
    rc, stdout, _ = await ops._run_git("branch")
    assert "aat/fix-003" not in stdout


@pytest.mark.asyncio
async def test_create_branch_duplicate_fails(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    original = await ops.current_branch()
    await ops.create_branch("aat/fix-dup")
    await ops.checkout(original)
    with pytest.raises(GitOpsError, match="Failed to create branch"):
        await ops.create_branch("aat/fix-dup")


# ---------------------------------------------------------------------------
# Tests: file + commit operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_file_changes(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)

    changes = [
        FileChange(path="src/app.py", original="", modified="print('hello')\n"),
    ]
    written = await ops.apply_file_changes(changes)

    assert len(written) == 1
    assert (tmp_path / "src" / "app.py").read_text() == "print('hello')\n"


@pytest.mark.asyncio
async def test_commit_changes(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)

    # Create a file to commit
    (tmp_path / "new.txt").write_text("new content")
    commit_hash = await ops.commit_changes(
        [tmp_path / "new.txt"], "add new file",
    )
    assert len(commit_hash) >= 7
    assert await ops.has_uncommitted_changes() is False


# ---------------------------------------------------------------------------
# Tests: on_fix_branch context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_fix_branch_returns_to_original(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    original = await ops.current_branch()

    async with ops.on_fix_branch("aat/fix-ctx"):
        assert await ops.current_branch() == "aat/fix-ctx"

    assert await ops.current_branch() == original


@pytest.mark.asyncio
async def test_on_fix_branch_returns_on_error(tmp_path: Path) -> None:
    await _init_git_repo(tmp_path)
    ops = GitOps(tmp_path)
    original = await ops.current_branch()

    with pytest.raises(ValueError, match="intentional"):
        async with ops.on_fix_branch("aat/fix-err"):
            raise ValueError("intentional error")

    assert await ops.current_branch() == original
