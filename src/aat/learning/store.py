"""LearnedStore — SQLite-based learning data storage."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from aat.core.exceptions import LearningError
from aat.core.models import LearnedElement

logger = logging.getLogger(__name__)

# A remembered coordinate is only reused while it is still trusted. Each click
# that turns out to do nothing knocks COORD_PENALTY off; below this floor the
# row is deleted rather than tried again.
MIN_COORD_CONFIDENCE = 0.5
COORD_PENALTY = 0.3

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

_CREATE_TABLE_FAILURES = """\
CREATE TABLE IF NOT EXISTS failure_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type      TEXT NOT NULL,
    error_message   TEXT NOT NULL,
    url_pattern     TEXT DEFAULT '',
    action          TEXT DEFAULT '',
    fix_description TEXT DEFAULT '',
    fix_applied     INTEGER DEFAULT 0,
    hit_count       INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_IDX_FAILURES = (
    "CREATE INDEX IF NOT EXISTS idx_failure_type ON failure_patterns(error_type, action);"
)

_CREATE_TABLE_PLATFORMS = """\
CREATE TABLE IF NOT EXISTS platform_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_key    TEXT NOT NULL,
    tip             TEXT NOT NULL,
    source          TEXT DEFAULT 'builtin',
    created_at      TEXT NOT NULL
);
"""

_CREATE_IDX_PLATFORMS = (
    "CREATE INDEX IF NOT EXISTS idx_platform_key ON platform_patterns(platform_key);"
)

_CREATE_TABLE_MATCH_HISTORY = """\
CREATE TABLE IF NOT EXISTS match_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name     TEXT NOT NULL,
    method          TEXT NOT NULL,
    success         INTEGER NOT NULL DEFAULT 1,
    confidence      REAL DEFAULT 0.0,
    elapsed_ms      REAL DEFAULT 0.0,
    tier            INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL
);
"""

_CREATE_IDX_MATCH_HISTORY = (
    "CREATE INDEX IF NOT EXISTS idx_match_target ON match_history(target_name, method);"
)

_CREATE_TABLE_STATE_COORDS = """\
CREATE TABLE IF NOT EXISTS state_coords (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name     TEXT NOT NULL,
    page_state      TEXT NOT NULL DEFAULT 'normal',
    correct_x       INTEGER NOT NULL,
    correct_y       INTEGER NOT NULL,
    confidence      REAL DEFAULT 1.0,
    use_count       INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_IDX_STATE_COORDS = (
    "CREATE INDEX IF NOT EXISTS idx_state_coords ON state_coords(target_name, page_state);"
)

_CREATE_TABLE_STRATEGIES = """\
CREATE TABLE IF NOT EXISTS test_strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    situation       TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    success_count   INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_IDX_STRATEGIES = (
    "CREATE INDEX IF NOT EXISTS idx_strategy_situation ON test_strategies(situation);"
)


def _row_to_element(row: sqlite3.Row) -> LearnedElement:
    """Convert a sqlite3.Row to a LearnedElement."""
    return LearnedElement(
        id=row["id"],
        scenario_id=row["scenario_id"],
        step_number=max(1, row["step_number"]),
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
            self._conn.execute(_CREATE_TABLE_FAILURES)
            self._conn.execute(_CREATE_IDX_FAILURES)
            self._conn.execute(_CREATE_TABLE_PLATFORMS)
            self._conn.execute(_CREATE_IDX_PLATFORMS)
            self._conn.execute(_CREATE_TABLE_MATCH_HISTORY)
            self._conn.execute(_CREATE_IDX_MATCH_HISTORY)
            self._conn.execute(_CREATE_TABLE_STATE_COORDS)
            self._conn.execute(_CREATE_IDX_STATE_COORDS)
            self._conn.execute(_CREATE_TABLE_STRATEGIES)
            self._conn.execute(_CREATE_IDX_STRATEGIES)
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

    def find_by_name(self, target_name: str) -> LearnedElement | None:
        """Find the most recently used element by target name."""
        try:
            row = self._conn.execute(
                """\
                SELECT * FROM learned_elements
                WHERE target_name=?
                ORDER BY use_count DESC, updated_at DESC
                LIMIT 1
                """,
                (target_name,),
            ).fetchone()
            if row is None:
                return None
            return _row_to_element(row)
        except sqlite3.Error:
            return None

    def save_or_update_by_name(
        self,
        target_name: str,
        x: int,
        y: int,
        confidence: float = 1.0,
    ) -> None:
        """Save or update learned coordinates by target name."""
        now = datetime.now(UTC).isoformat()
        try:
            # Duplicate coordinate check: warn if another target has same coords
            dup_row = self._conn.execute(
                "SELECT target_name FROM learned_elements "
                "WHERE correct_x=? AND correct_y=? AND target_name!=? "
                "LIMIT 1",
                (x, y, target_name),
            ).fetchone()
            if dup_row:
                logger.warning(
                    "Duplicate coords (%d,%d): '%s' conflicts with '%s'",
                    x,
                    y,
                    target_name,
                    dup_row["target_name"],
                )

            existing = self.find_by_name(target_name)
            if existing and existing.id is not None:
                # Update if coordinates changed
                if existing.correct_x != x or existing.correct_y != y:
                    self._conn.execute(
                        """\
                        UPDATE learned_elements
                        SET correct_x=?, correct_y=?, confidence=?,
                            use_count=use_count+1, updated_at=?
                        WHERE id=?
                        """,
                        (x, y, confidence, now, existing.id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE learned_elements "
                        "SET use_count=use_count+1, updated_at=? WHERE id=?",
                        (now, existing.id),
                    )
                self._conn.commit()
            else:
                self._conn.execute(
                    """\
                    INSERT INTO learned_elements
                        (scenario_id, step_number, target_name,
                         screenshot_hash, correct_x, correct_y,
                         cropped_image, confidence, use_count,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("_auto", 1, target_name, "", x, y, "", confidence, 1, now, now),
                )
                self._conn.commit()
        except sqlite3.Error:
            pass

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

    # -- Failure Patterns ----------------------------------------------------

    def record_failure(
        self,
        error_type: str,
        error_message: str,
        url_pattern: str = "",
        action: str = "",
        fix_description: str = "",
    ) -> None:
        """실패 패턴을 기록한다. 동일한 error_type + action이 있으면 hit_count를 증가시킨다."""
        now = datetime.now(UTC).isoformat()
        try:
            cursor = self._conn.execute(
                "SELECT id FROM failure_patterns WHERE error_type = ? AND action = ? LIMIT 1",
                (error_type, action),
            )
            row = cursor.fetchone()

            if row:
                self._conn.execute(
                    "UPDATE failure_patterns"
                    " SET hit_count = hit_count + 1, updated_at = ?, error_message = ?"
                    " WHERE id = ?",
                    (now, error_message, row["id"]),
                )
            else:
                self._conn.execute(
                    """\
                    INSERT INTO failure_patterns
                        (error_type, error_message, url_pattern, action,
                         fix_description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (error_type, error_message, url_pattern, action, fix_description, now, now),
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"record_failure failed: {exc}"
            raise LearningError(msg) from exc

    def find_similar_failure(self, error_type: str, action: str = "") -> dict[str, Any] | None:
        """fix가 적용된 동일 유형의 실패 패턴을 반환한다."""
        try:
            cursor = self._conn.execute(
                """\
                SELECT error_type, error_message, fix_description, hit_count
                FROM failure_patterns
                WHERE error_type = ? AND fix_applied = 1
                ORDER BY hit_count DESC
                LIMIT 1
                """,
                (error_type,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "error_type": row["error_type"],
                    "error_message": row["error_message"],
                    "fix_description": row["fix_description"],
                    "hit_count": row["hit_count"],
                }
            return None
        except sqlite3.Error as exc:
            msg = f"find_similar_failure failed: {exc}"
            raise LearningError(msg) from exc

    def mark_fix_applied(self, error_type: str, fix_description: str) -> None:
        """해당 error_type의 실패 패턴에 fix 적용 완료를 표시한다."""
        now = datetime.now(UTC).isoformat()
        try:
            self._conn.execute(
                "UPDATE failure_patterns"
                " SET fix_applied = 1, fix_description = ?, updated_at = ?"
                " WHERE error_type = ?",
                (fix_description, now, error_type),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"mark_fix_applied failed: {exc}"
            raise LearningError(msg) from exc

    def get_failure_stats(self) -> list[dict[str, Any]]:
        """실패 패턴 통계를 hit_count 내림차순으로 반환한다 (최대 20개)."""
        try:
            cursor = self._conn.execute(
                """\
                SELECT error_type, hit_count, fix_applied, fix_description
                FROM failure_patterns
                ORDER BY hit_count DESC
                LIMIT 20
                """
            )
            return [
                {
                    "error_type": row["error_type"],
                    "hit_count": row["hit_count"],
                    "fix_applied": bool(row["fix_applied"]),
                    "fix_description": row["fix_description"],
                }
                for row in cursor.fetchall()
            ]
        except sqlite3.Error as exc:
            msg = f"get_failure_stats failed: {exc}"
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

    def export_data(self, output_path: Path) -> int:
        """learned_elements와 failure_patterns 전체를 JSON으로 내보낸다."""
        try:
            cursor = self._conn.execute("SELECT * FROM learned_elements")
            columns = [desc[0] for desc in cursor.description]
            elements = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

            cursor = self._conn.execute("SELECT * FROM failure_patterns")
            columns = [desc[0] for desc in cursor.description]
            failures = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            msg = f"export_data query failed: {exc}"
            raise LearningError(msg) from exc

        data = {
            "version": 1,
            "learned_elements": elements,
            "failure_patterns": failures,
        }
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            msg = f"Failed to write export file: {output_path}"
            raise LearningError(msg) from exc

        return len(elements) + len(failures)

    def import_data(self, input_path: Path) -> int:
        """JSON 파일에서 learned_elements와 failure_patterns를 병합 가져오기한다."""
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Failed to read import file: {input_path}"
            raise LearningError(msg) from exc

        imported = 0
        try:
            for elem in data.get("learned_elements", []):
                try:
                    self._conn.execute(
                        """\
                        INSERT OR IGNORE INTO learned_elements
                            (scenario_id, step_number, target_name, screenshot_hash,
                             correct_x, correct_y, cropped_image, confidence,
                             use_count, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            elem.get("scenario_id", ""),
                            elem.get("step_number", 0),
                            elem.get("target_name", ""),
                            elem.get("screenshot_hash", ""),
                            elem.get("correct_x", 0),
                            elem.get("correct_y", 0),
                            elem.get("cropped_image", ""),
                            elem.get("confidence", 1.0),
                            elem.get("use_count", 0),
                            elem.get("created_at", ""),
                            elem.get("updated_at", ""),
                        ),
                    )
                    imported += 1
                except sqlite3.Error:
                    continue

            for fp in data.get("failure_patterns", []):
                try:
                    self._conn.execute(
                        """\
                        INSERT OR IGNORE INTO failure_patterns
                            (error_type, error_message, url_pattern, action,
                             fix_description, fix_applied, hit_count,
                             created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fp.get("error_type", ""),
                            fp.get("error_message", ""),
                            fp.get("url_pattern", ""),
                            fp.get("action", ""),
                            fp.get("fix_description", ""),
                            fp.get("fix_applied", 0),
                            fp.get("hit_count", 0),
                            fp.get("created_at", ""),
                            fp.get("updated_at", ""),
                        ),
                    )
                    imported += 1
                except sqlite3.Error:
                    continue

            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"import_data failed: {exc}"
            raise LearningError(msg) from exc

        return imported

    # -- Platform patterns -----------------------------------------------------

    def add_platform_tip(
        self,
        platform_key: str,
        tip: str,
        source: str = "user",
    ) -> None:
        """Add a custom platform-specific tip."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO platform_patterns "
            "(platform_key, tip, source, created_at) VALUES (?, ?, ?, ?)",
            (platform_key, tip, source, now),
        )
        self._conn.commit()

    def get_platform_tips(self, platform_key: str) -> list[str]:
        """Get all tips for a platform (builtin + user-added)."""
        cursor = self._conn.execute(
            "SELECT tip FROM platform_patterns WHERE platform_key = ? ORDER BY id",
            (platform_key,),
        )
        return [row["tip"] for row in cursor.fetchall()]

    def list_platform_patterns(self) -> list[dict[str, Any]]:
        """List all platform patterns grouped by platform."""
        cursor = self._conn.execute(
            "SELECT platform_key, tip, source, created_at "
            "FROM platform_patterns ORDER BY platform_key, id"
        )
        return [
            {
                "platform": row["platform_key"],
                "tip": row["tip"],
                "source": row["source"],
                "created_at": row["created_at"],
            }
            for row in cursor.fetchall()
        ]

    # -- Match History ---------------------------------------------------------

    def record_match(
        self,
        target_name: str,
        method: str,
        success: bool,
        confidence: float = 0.0,
        elapsed_ms: float = 0.0,
        tier: int = 1,
    ) -> None:
        """Record a match attempt result for learning."""
        now = datetime.now(UTC).isoformat()
        try:
            self._conn.execute(
                """\
                INSERT INTO match_history
                    (target_name, method, success, confidence, elapsed_ms, tier, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (target_name, method, 1 if success else 0, confidence, elapsed_ms, tier, now),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("record_match failed: %s", exc)

    def get_best_method(self, target_name: str) -> str | None:
        """Get the most successful method for a target (by success rate, then speed).

        Returns method name or None if no history.
        """
        try:
            cursor = self._conn.execute(
                """\
                SELECT method,
                       SUM(success) AS wins,
                       COUNT(*) AS total,
                       AVG(elapsed_ms) AS avg_ms
                FROM match_history
                WHERE target_name = ?
                GROUP BY method
                HAVING wins > 0
                ORDER BY CAST(wins AS REAL) / total DESC, avg_ms ASC
                LIMIT 1
                """,
                (target_name,),
            )
            row = cursor.fetchone()
            if row:
                return str(row["method"])
        except sqlite3.Error as exc:
            logger.warning("get_best_method failed: %s", exc)
        return None

    def get_match_stats(self) -> list[dict[str, Any]]:
        """Get match history stats grouped by target and method."""
        try:
            cursor = self._conn.execute(
                """\
                SELECT target_name, method,
                       SUM(success) AS wins,
                       COUNT(*) AS total,
                       AVG(confidence) AS avg_conf,
                       AVG(elapsed_ms) AS avg_ms
                FROM match_history
                GROUP BY target_name, method
                ORDER BY target_name, wins DESC
                """
            )
            return [
                {
                    "target": row["target_name"],
                    "method": row["method"],
                    "wins": row["wins"],
                    "total": row["total"],
                    "avg_confidence": round(row["avg_conf"], 3),
                    "avg_ms": round(row["avg_ms"], 1),
                }
                for row in cursor.fetchall()
            ]
        except sqlite3.Error as exc:
            logger.warning("get_match_stats failed: %s", exc)
            return []

    def get_target_failure_count(self, target_name: str) -> int:
        """Count failures for a specific target."""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM match_history WHERE target_name=? AND success=0",
                (target_name,),
            ).fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error:
            return 0

    # -- State-aware coordinates -----------------------------------------------

    def find_state_coords(
        self,
        target_name: str,
        page_state: str = "normal",
    ) -> tuple[int, int, float] | None:
        """Find coordinates for target in given page state.

        Rows whose confidence has decayed below MIN_COORD_CONFIDENCE are
        ignored: a coordinate that stopped working must not keep being tried.

        Returns (x, y, confidence) or None.
        """
        try:
            row = self._conn.execute(
                """\
                SELECT correct_x, correct_y, confidence
                FROM state_coords
                WHERE target_name=? AND page_state=? AND confidence>=?
                ORDER BY use_count DESC
                LIMIT 1
                """,
                (target_name, page_state, MIN_COORD_CONFIDENCE),
            ).fetchone()
            if row:
                return row["correct_x"], row["correct_y"], row["confidence"]
        except sqlite3.Error:
            pass
        return None

    def save_state_coords(
        self,
        target_name: str,
        page_state: str,
        x: int,
        y: int,
        confidence: float = 1.0,
    ) -> None:
        """Save or update coordinates for target + state combination."""
        now = datetime.now(UTC).isoformat()
        try:
            row = self._conn.execute(
                "SELECT id, correct_x, correct_y FROM state_coords "
                "WHERE target_name=? AND page_state=?",
                (target_name, page_state),
            ).fetchone()

            if row:
                if row["correct_x"] != x or row["correct_y"] != y:
                    self._conn.execute(
                        "UPDATE state_coords "
                        "SET correct_x=?, correct_y=?, confidence=?, "
                        "use_count=use_count+1, updated_at=? WHERE id=?",
                        (x, y, confidence, now, row["id"]),
                    )
                else:
                    self._conn.execute(
                        "UPDATE state_coords SET use_count=use_count+1, updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO state_coords "
                    "(target_name, page_state, correct_x, correct_y, "
                    "confidence, use_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (target_name, page_state, x, y, confidence, now, now),
                )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def penalize_coords(
        self,
        target_name: str,
        page_state: str | None = None,
        penalty: float = COORD_PENALTY,
    ) -> int:
        """Lower the confidence of remembered coordinates that did not work.

        Called when a click on a remembered position produced no screen change.
        Rows falling below MIN_COORD_CONFIDENCE are deleted, so the next run
        searches for the element again instead of repeating the same mistake.

        Args:
            target_name: Target whose memory is suspect.
            page_state: Restrict to one page state, or None for every state.
            penalty: Confidence subtracted from each matching row.

        Returns:
            Number of rows deleted.
        """
        now = datetime.now(UTC).isoformat()
        try:
            if page_state is None:
                self._conn.execute(
                    "UPDATE state_coords SET confidence=confidence-?, updated_at=? "
                    "WHERE target_name=?",
                    (penalty, now, target_name),
                )
            else:
                self._conn.execute(
                    "UPDATE state_coords SET confidence=confidence-?, updated_at=? "
                    "WHERE target_name=? AND page_state=?",
                    (penalty, now, target_name, page_state),
                )
            cursor = self._conn.execute(
                "DELETE FROM state_coords WHERE target_name=? AND confidence<?",
                (target_name, MIN_COORD_CONFIDENCE),
            )
            deleted = cursor.rowcount or 0
            self._conn.execute(
                "UPDATE learned_elements SET confidence=confidence-? WHERE target_name=?",
                (penalty, target_name),
            )
            cursor = self._conn.execute(
                "DELETE FROM learned_elements WHERE target_name=? AND confidence<?",
                (target_name, MIN_COORD_CONFIDENCE),
            )
            deleted += cursor.rowcount or 0
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("penalize_coords failed: %s", exc)
            return 0
        return deleted

    def list_state_coords(self) -> list[dict[str, Any]]:
        """List every remembered coordinate, most-used first."""
        try:
            cursor = self._conn.execute(
                "SELECT target_name, page_state, correct_x, correct_y, "
                "confidence, use_count, updated_at FROM state_coords "
                "ORDER BY use_count DESC, target_name"
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            logger.warning("list_state_coords failed: %s", exc)
            return []

    def forget_coords(self, target_name: str | None = None) -> int:
        """Delete remembered coordinates by target name (all of them if None).

        Returns:
            Number of rows deleted across state_coords and learned_elements.
        """
        try:
            if target_name is None:
                deleted = self._conn.execute("DELETE FROM state_coords").rowcount or 0
                deleted += self._conn.execute("DELETE FROM learned_elements").rowcount or 0
            else:
                deleted = (
                    self._conn.execute(
                        "DELETE FROM state_coords WHERE target_name=?",
                        (target_name,),
                    ).rowcount
                    or 0
                )
                deleted += (
                    self._conn.execute(
                        "DELETE FROM learned_elements WHERE target_name=?",
                        (target_name,),
                    ).rowcount
                    or 0
                )
            self._conn.commit()
        except sqlite3.Error as exc:
            msg = f"forget_coords failed: {exc}"
            raise LearningError(msg) from exc
        return deleted

    # -- Test strategies --------------------------------------------------------

    def learn_strategy(
        self,
        situation: str,
        strategy: str,
        success: bool = True,
    ) -> None:
        """Record a test strategy for a given situation.

        If the same situation+strategy exists, update counts.
        """
        now = datetime.now(UTC).isoformat()
        try:
            row = self._conn.execute(
                "SELECT id, success_count, fail_count FROM test_strategies "
                "WHERE situation=? AND strategy=?",
                (situation, strategy),
            ).fetchone()

            if row:
                if success:
                    self._conn.execute(
                        "UPDATE test_strategies "
                        "SET success_count=success_count+1, updated_at=? "
                        "WHERE id=?",
                        (now, row["id"]),
                    )
                else:
                    self._conn.execute(
                        "UPDATE test_strategies "
                        "SET fail_count=fail_count+1, updated_at=? "
                        "WHERE id=?",
                        (now, row["id"]),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO test_strategies "
                    "(situation, strategy, success_count, fail_count, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        situation,
                        strategy,
                        1 if success else 0,
                        0 if success else 1,
                        now,
                        now,
                    ),
                )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def get_strategies(self, situation: str) -> list[dict[str, Any]]:
        """Get strategies for a situation, sorted by success rate."""
        try:
            rows = self._conn.execute(
                """\
                SELECT strategy, success_count, fail_count
                FROM test_strategies
                WHERE situation=?
                ORDER BY
                    CAST(success_count AS REAL) /
                    MAX(success_count + fail_count, 1) DESC,
                    success_count DESC
                """,
                (situation,),
            ).fetchall()
            return [
                {
                    "strategy": r["strategy"],
                    "success": r["success_count"],
                    "fail": r["fail_count"],
                }
                for r in rows
            ]
        except sqlite3.Error:
            return []

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
