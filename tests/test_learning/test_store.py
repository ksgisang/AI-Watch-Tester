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


# ── Host scoping (AAT-115) ───────────────────────────────────────────────────


class TestHostScoping:
    """A position learned on one application is not evidence about another.

    The picture bank was scoped by host from the start; coordinates were not,
    so a click learned against ``127.0.0.1`` was replayed against
    ``localhost`` -- two names for one machine, but routinely two different
    products on a developer's laptop, and certainly two different products
    across hosts. These tests pin the key, not just the stored value: the bug
    that mattered was the *lookup* ignoring the host.
    """

    def test_a_position_is_only_found_on_the_host_it_was_learned_on(
        self, store: LearnedStore
    ) -> None:
        store.save_state_coords("grade", "normal", 10, 20, host="a.example")

        assert store.find_state_coords("grade", "normal", host="a.example") == (10, 20, 1.0)
        assert store.find_state_coords("grade", "normal", host="b.example") is None

    def test_the_state_agnostic_lookup_is_scoped_too(self, store: LearnedStore) -> None:
        store.save_or_update_by_name("grade", 10, 20, host="a.example")

        found = store.find_by_name("grade", host="a.example")
        assert found is not None
        assert (found.correct_x, found.correct_y) == (10, 20)
        assert store.find_by_name("grade", host="b.example") is None

    def test_two_hosts_keep_separate_positions_under_one_name(self, store: LearnedStore) -> None:
        """The failure mode if ``host`` were in the row but not in the lookup.

        ``save_state_coords`` updates-or-inserts. Looking up without the host
        would find the other host's row, overwrite its position -- corrupting
        that host's memory -- and leave this host with none of its own, so
        learning would silently never take hold on the second application.
        """
        store.save_state_coords("submit", "normal", 10, 20, host="a.example")
        store.save_state_coords("submit", "normal", 300, 400, host="b.example")

        assert store.find_state_coords("submit", "normal", host="a.example") == (10, 20, 1.0)
        assert store.find_state_coords("submit", "normal", host="b.example") == (300, 400, 1.0)

    def test_penalising_one_host_leaves_the_other_alone(self, store: LearnedStore) -> None:
        """A click that did nothing indicts one application, not every one."""
        store.save_state_coords("submit", "normal", 10, 20, confidence=0.6, host="a.example")
        store.save_state_coords("submit", "normal", 300, 400, confidence=0.6, host="b.example")

        store.penalize_coords("submit", "normal", host="a.example")

        assert store.find_state_coords("submit", "normal", host="a.example") is None
        assert store.find_state_coords("submit", "normal", host="b.example") == (300, 400, 0.6)

    def test_the_listing_shows_which_host_each_position_belongs_to(
        self, store: LearnedStore
    ) -> None:
        store.save_state_coords("submit", "normal", 10, 20, host="a.example")

        rows = store.list_state_coords()
        assert [r["host"] for r in rows] == ["a.example"]


class TestLegacyRowsAreInert:
    """Rows that predate host scoping are kept, listed, and never reused.

    Deleting a user's accumulated learning without being asked is not the
    migration's call. Reusing it is worse: an unknown origin is not evidence
    about the screen in front of us. So the migration writes an empty host,
    which no read ever asks for.
    """

    def test_a_row_with_no_host_answers_no_lookup(self, tmp_path: Path) -> None:
        import sqlite3

        db = tmp_path / "legacy.db"
        store = LearnedStore(db)
        store.close()

        # Forge the pre-migration shape: a position with no provenance.
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO state_coords "
            "(target_name, page_state, correct_x, correct_y, confidence, use_count, "
            "host, created_at, updated_at) VALUES ('grade','normal',10,20,1.0,5,'','','')"
        )
        conn.commit()
        conn.close()

        store = LearnedStore(db)
        try:
            assert store.find_state_coords("grade", "normal", host="a.example") is None
            assert store.find_state_coords("grade", "normal") is None
            # Still visible, so a user can see why a run stopped recognising it.
            assert [r["target_name"] for r in store.list_state_coords()] == ["grade"]
        finally:
            store.close()

    def test_an_existing_database_gains_the_column_and_keeps_its_rows(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The upgrade path: ALTER, not recreate, so learning survives it."""
        import logging
        import sqlite3

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE state_coords ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, target_name TEXT NOT NULL, "
            "page_state TEXT NOT NULL, correct_x INTEGER NOT NULL, "
            "correct_y INTEGER NOT NULL, confidence REAL NOT NULL DEFAULT 1.0, "
            "use_count INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO state_coords "
            "(target_name, page_state, correct_x, correct_y, created_at, updated_at) "
            "VALUES ('grade','normal',10,20,'','')"
        )
        conn.commit()
        conn.close()

        with caplog.at_level(logging.WARNING):
            store = LearnedStore(db)
        try:
            rows = store.list_state_coords()
            assert len(rows) == 1, "the upgrade must not discard what was learned"
            assert rows[0]["host"] == ""
            assert store.find_state_coords("grade", "normal", host="a.example") is None
        finally:
            store.close()

        # The user is told, once, and told what to run.
        assert "aat learn reset --all" in caplog.text

    def test_the_warning_fires_only_once_per_database(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        db = tmp_path / "twice.db"
        LearnedStore(db).close()

        with caplog.at_level(logging.WARNING):
            store = LearnedStore(db)
            store.close()

        assert "predate host scoping" not in caplog.text
