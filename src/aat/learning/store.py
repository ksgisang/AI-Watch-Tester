"""LearnedStore — SQLite-based learning data storage."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path  # noqa: TC003

from aat.core.exceptions import LearningError
from aat.core.models import LearnedElement

logger = logging.getLogger(__name__)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS learned_elements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id     TEXT NOT NULL,
    step_number     INTEGER NOT NULL,
    target_name     TEXT NOT NULL,
    screenshot_hash TEXT NOT NULL,
    correct_x       INTEGER NOT NULL,
    correct_y       INTEGER NOT NULL,
    cropped_image   TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    use_count       INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_IDX_TARGET = (
    "CREATE INDEX IF NOT EXISTS idx_learned_target "
    "ON learned_elements(scenario_id, step_number, target_name);"
)

_CREATE_IDX_HASH = (
    "CREATE INDEX IF NOT EXISTS idx_learned_hash ON learned_elements(screenshot_hash);"
)


def _row_to_element(row: sqlite3.Row) -> LearnedElement:
    """Convert a sqlite3.Row to a LearnedElement."""
    return LearnedElement(
        id=row["id"],
        scenario_id=row["scenario_id"],
        step_number=row["step_number"],
        target_name=row["target_name"],
        screenshot_hash=row["screenshot_hash"],
        correct_x=row["correct_x"],
        correct_y=row["correct_y"],
        cropped_image_path=row["cropped_image"],
        confidence=row["confidence"],
        use_count=row["use_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class LearnedStore:
    """SQLite-backed store for learned element positions."""

    def __init__(self, db_path: Path) -> None:
        """Open or create the SQLite database at *db_path*."""
        try:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_IDX_TARGET)
            self._conn.execute(_CREATE_IDX_HASH)
            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"Failed to open database: {db_path}"
            raise LearningError(msg) from exc

    # -- CRUD ----------------------------------------------------------------

    def save(self, element: LearnedElement) -> LearnedElement:
        """Insert or update an element. Returns element with id populated."""
        now = datetime.now().isoformat()
        try:
            if element.id is not None:
                self._conn.execute(
                    """\
                    UPDATE learned_elements
                    SET scenario_id=?, step_number=?, target_name=?,
                        screenshot_hash=?, correct_x=?, correct_y=?,
                        cropped_image=?, confidence=?, use_count=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        element.scenario_id,
                        element.step_number,
                        element.target_name,
                        element.screenshot_hash,
                        element.correct_x,
                        element.correct_y,
                        element.cropped_image_path,
                        element.confidence,
                        element.use_count,
                        now,
                        element.id,
                    ),
                )
                self._conn.commit()
                return element.model_copy(
                    update={"updated_at": datetime.fromisoformat(now)},
                )

            cursor = self._conn.execute(
                """\
                INSERT INTO learned_elements
                    (scenario_id, step_number, target_name, screenshot_hash,
                     correct_x, correct_y, cropped_image, confidence,
                     use_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    element.scenario_id,
                    element.step_number,
                    element.target_name,
                    element.screenshot_hash,
                    element.correct_x,
                    element.correct_y,
                    element.cropped_image_path,
                    element.confidence,
                    element.use_count,
                    element.created_at.isoformat(),
                    now,
                ),
            )
            self._conn.commit()
            return element.model_copy(
                update={
                    "id": cursor.lastrowid,
                    "updated_at": datetime.fromisoformat(now),
                },
            )
        except sqlite3.Error as exc:
            msg = f"Failed to save element: {exc}"
            raise LearningError(msg) from exc

    def find_by_target(
        self,
        scenario_id: str,
        step_number: int,
        target_name: str,
    ) -> LearnedElement | None:
        """Find element by scenario + step + target name."""
        try:
            row = self._conn.execute(
                """\
                SELECT * FROM learned_elements
                WHERE scenario_id=? AND step_number=? AND target_name=?
                ORDER BY confidence DESC
                LIMIT 1
                """,
                (scenario_id, step_number, target_name),
            ).fetchone()
            if row is None:
                return None
            return _row_to_element(row)
        except sqlite3.Error as exc:
            msg = f"find_by_target failed: {exc}"
            raise LearningError(msg) from exc

    def find_by_hash(self, screenshot_hash: str) -> list[LearnedElement]:
        """Find all elements matching a screenshot hash."""
        try:
            rows = self._conn.execute(
                "SELECT * FROM learned_elements WHERE screenshot_hash=?",
                (screenshot_hash,),
            ).fetchall()
            return [_row_to_element(r) for r in rows]
        except sqlite3.Error as exc:
            msg = f"find_by_hash failed: {exc}"
            raise LearningError(msg) from exc

    def delete(self, element_id: int) -> bool:
        """Delete element by id. Returns True if a row was deleted."""
        try:
            cursor = self._conn.execute(
                "DELETE FROM learned_elements WHERE id=?",
                (element_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            msg = f"delete failed: {exc}"
            raise LearningError(msg) from exc

    def list_all(self) -> list[LearnedElement]:
        """Return all stored elements."""
        try:
            rows = self._conn.execute(
                "SELECT * FROM learned_elements ORDER BY id",
            ).fetchall()
            return [_row_to_element(r) for r in rows]
        except sqlite3.Error as exc:
            msg = f"list_all failed: {exc}"
            raise LearningError(msg) from exc

    def increment_use_count(self, element_id: int) -> None:
        """Increment use_count by 1 for the given element."""
        now = datetime.now().isoformat()
        try:
            self._conn.execute(
                "UPDATE learned_elements SET use_count=use_count+1, updated_at=? WHERE id=?",
                (now, element_id),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"increment_use_count failed: {exc}"
            raise LearningError(msg) from exc

    # -- Import / Export -----------------------------------------------------

    def export_json(self, path: Path) -> None:
        """Export all elements to a JSON file."""
        elements = self.list_all()
        data = [e.model_dump(mode="json") for e in elements]
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            msg = f"Failed to export JSON: {path}"
            raise LearningError(msg) from exc

    def import_json(self, path: Path) -> int:
        """Import elements from a JSON file. Returns count imported."""
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Failed to import JSON: {path}"
            raise LearningError(msg) from exc

        count = 0
        for item in data:
            # Strip the id so save() inserts a new row
            item.pop("id", None)
            element = LearnedElement(**item)
            self.save(element)
            count += 1
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
