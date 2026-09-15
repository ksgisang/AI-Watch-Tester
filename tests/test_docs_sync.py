"""Guard the agent skill's schema reference against drifting from the models.

The reference was hand-maintained once and went quietly stale: it described 18
actions while the code had 26, so an AI reading it could not write a step that
the code already supported. Nothing failed — the docs simply lied. This test is
the alarm that was missing.

`awt-skill` is a git submodule, so the files may be absent (CI checks out the
main repo without submodules). The check is skipped then rather than failed:
absent is not stale.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "gen_scenario_schema.py"
SKILL_ROOT = REPO_ROOT / "awt-skill" / "awt"

needs_skill = pytest.mark.skipif(
    not SKILL_ROOT.is_dir(),
    reason="awt-skill submodule is not checked out",
)


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_scenario_schema", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass() looks the module up in sys.modules while building the class.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@needs_skill
def test_skill_docs_match_models() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "The agent skill's scenario docs no longer match src/aat/core/models.py.\n"
        f"{result.stdout}{result.stderr}"
    )


@needs_skill
def test_generation_is_idempotent() -> None:
    """Generating twice must produce the same text.

    Output that shifts on every run would make the check above fire forever and
    train everyone to ignore it. Compared in memory, so the repo is untouched.
    """
    gen = _generator()
    wanted_files = gen.targets()
    assert wanted_files is not None
    # targets() derives SKILL.md from what is already on disk, so agreeing with
    # disk means re-generating an already-generated file changes nothing.
    for path, wanted in wanted_files:
        assert path.read_text() == wanted, f"{path.name} is not what the generator wants"
