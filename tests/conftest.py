"""Shared test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aat.matchers import template_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_template_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Keep the template store out of the developer's real home directory.

    Autouse and unconditional. The store's directory used to be a module-level
    constant pointing at ``~/.awt/templates``, and the suite wrote into it: of
    the 109 files found there, 107 were byte-identical 210x60 fixtures from
    ``tests/``, and only 2 came from a real run. That is not only clutter — a
    test fixture sitting in the store is a picture that a *real* run can heal
    from, so the suite was quietly able to change how the product behaves on
    the machine that ran it.

    Opting in per test would not fix that, because the tests that pollute it
    are the ones that never thought about it.
    """
    store = tmp_path / "templates"
    monkeypatch.setenv(template_store.ENV_DIR, str(store))
    yield store
