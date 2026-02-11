"""Tests for LearnedStore."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path  # noqa: TC003

import pytest

from aat.core.models import LearnedElement
from aat.learning.store import LearnedStore


def _make_element(**overrides: object) -> LearnedElement:
    """Create a LearnedElement with sensible defaults."""
    defaults: dict[str, object] = {
        "scenario_id": "SC-001",
        "step_number": 1,
        "target_name": "login_button",
        "screenshot_hash": "abc123hash",
        "correct_x": 100,
        "correct_y": 200,
        "cropped_image_path": "/tmp/crop.png",
        "confidence": 0.95,
        "use_count": 0,
        "created_at": datetime(2025, 1, 1, 12, 0, 0),
        "updated_at": datetime(2025, 1, 1, 12, 0, 0),
    }
    defaults.update(overrides)
    return LearnedElement(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def store(tmp_path: Path) -> LearnedStore:
    s = LearnedStore(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    s.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────


class TestCRUD:
    def test_save_and_retrieve(self, store: LearnedStore) -> None:
        elem = _make_element()
        saved = store.save(elem)

        assert saved.id is not None
        assert saved.id >= 1
        assert saved.scenario_id == "SC-001"

    def test_save_update(self, store: LearnedStore) -> None:
        elem = _make_element()
        saved = store.save(elem)
        assert saved.id is not None

        updated = saved.model_copy(update={"confidence": 0.99})
        result = store.save(updated)
        assert result.confidence == 0.99

        # Only one row in the DB
        assert len(store.list_all()) == 1

    def test_find_by_target(self, store: LearnedStore) -> None:
        store.save(_make_element())

        found = store.find_by_target("SC-001", 1, "login_button")
        assert found is not None
        assert found.target_name == "login_button"

    def test_find_by_target_not_found(self, store: LearnedStore) -> None:
        result = store.find_by_target("SC-999", 1, "nope")
        assert result is None

    def test_find_by_hash(self, store: LearnedStore) -> None:
        store.save(_make_element(screenshot_hash="hash1"))
        store.save(_make_element(screenshot_hash="hash1", target_name="other"))
        store.save(_make_element(screenshot_hash="hash2"))

        results = store.find_by_hash("hash1")
        assert len(results) == 2

    def test_delete(self, store: LearnedStore) -> None:
        saved = store.save(_make_element())
        assert saved.id is not None

        assert store.delete(saved.id) is True
        assert store.list_all() == []

    def test_delete_nonexistent(self, store: LearnedStore) -> None:
        assert store.delete(9999) is False

    def test_list_all(self, store: LearnedStore) -> None:
        store.save(_make_element(target_name="a"))
        store.save(_make_element(target_name="b"))

        all_elems = store.list_all()
        assert len(all_elems) == 2


# ── increment_use_count ──────────────────────────────────────────────────────


class TestIncrementUseCount:
    def test_increment(self, store: LearnedStore) -> None:
        saved = store.save(_make_element(use_count=0))
        assert saved.id is not None

        store.increment_use_count(saved.id)
        store.increment_use_count(saved.id)

        found = store.find_by_target("SC-001", 1, "login_button")
        assert found is not None
        assert found.use_count == 2


# ── JSON export / import ─────────────────────────────────────────────────────


class TestJsonExportImport:
    def test_export_import_roundtrip(self, store: LearnedStore, tmp_path: Path) -> None:
        store.save(_make_element(target_name="btn1"))
        store.save(_make_element(target_name="btn2"))

        json_path = tmp_path / "export.json"
        store.export_json(json_path)
        assert json_path.exists()

        # Create a fresh store and import
        store2 = LearnedStore(tmp_path / "test2.db")
        try:
            count = store2.import_json(json_path)
            assert count == 2
            assert len(store2.list_all()) == 2
        finally:
            store2.close()
