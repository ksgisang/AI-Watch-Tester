"""Tests for ``aat learned`` — what AWT remembers, and how to forget it.

Two things are being pinned here. First, that banked element pictures are
*visible*: they are the only reason a broken selector heals, and a store the
user cannot inspect is a store they cannot trust. Second, that forgetting is
targeted — ``--templates`` must not wipe remembered coordinates, and
``--host`` must not wipe other hosts. Clearing more than was asked for throws
away working knowledge, and the user finds out only when a later run fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from aat.cli.main import app
from aat.matchers import template_store

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path) -> Iterator[Path]:
    """Point the command at an empty data directory.

    Without this the command loads the real config and reads the developer's
    own ``.aat/learned.db``, so the assertions would depend on whatever that
    machine happened to have learned.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cfg = MagicMock()
    cfg.data_dir = str(data_dir)
    with patch("aat.cli.commands.learned_cmd.load_config", return_value=cfg):
        yield data_dir


def _bank(target: str, host: str = "example.com", *, width: int = 80, height: int = 30) -> None:
    """Put one picture in the store the way a real run would."""
    img = np.full((240, 320, 3), 40, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    saved = template_store.save(
        template_store.scope_for_host(host),
        target,
        buf.tobytes(),
        left=40,
        top=50,
        width=width,
        height=height,
        method="selector",
        confidence=0.95,
    )
    assert saved is not None, "the fixture itself must bank something"


class TestList:
    def test_banked_pictures_are_listed_with_their_host(self) -> None:
        _bank("Submit", "app.example.com")
        _bank("로그인", "localhost:3000")

        result = runner.invoke(app, ["learned", "list"])

        assert result.exit_code == 0
        assert "Banked Element Pictures" in result.output
        assert "app.example.com" in result.output
        assert "Submit" in result.output
        # The host a run banked against is the host the user types to clear it.
        assert "localhost_3000" in result.output
        assert "로그인" in result.output

    def test_the_size_and_age_of_each_picture_are_shown(self) -> None:
        _bank("Submit", width=80, height=30)

        result = runner.invoke(app, ["learned", "list"])

        # Padded on every side, so the stored crop is larger than the element.
        assert f"{80 + 2 * template_store.PAD}x{30 + 2 * template_store.PAD}" in result.output
        assert "0.0d" in result.output

    def test_pictures_show_up_without_a_learning_database(self, _isolate_config: Path) -> None:
        """The two stores are independent and the report must say so.

        A run that never learned a coordinate writes no ``learned.db``. The
        command used to return as soon as that file was missing, so a user with
        a store full of pictures was told "No learned data yet" -- a green light
        that contradicted the disk.
        """
        assert not (_isolate_config / "learned.db").exists()
        _bank("Submit")

        result = runner.invoke(app, ["learned", "list"])

        assert result.exit_code == 0
        assert "Submit" in result.output
        assert "No learned data yet" not in result.output

    def test_the_table_is_capped_and_says_how_much_it_hid(self) -> None:
        for i in range(23):
            _bank(f"Button {i}")

        result = runner.invoke(app, ["learned", "list"])

        assert "… and 3 more" in result.output

    def test_the_way_to_remove_them_is_printed(self) -> None:
        _bank("Submit")

        result = runner.invoke(app, ["learned", "list"])

        assert "aat learned clear --templates" in result.output

    def test_an_empty_store_says_there_is_nothing(self) -> None:
        result = runner.invoke(app, ["learned", "list"])

        assert result.exit_code == 0
        assert "No learned data yet" in result.output

    def test_an_unreadable_picture_store_does_not_kill_the_report(self) -> None:
        """Listing is a report, and a partial report beats a traceback."""
        with patch.object(template_store, "inventory", side_effect=OSError("disk gone")):
            result = runner.invoke(app, ["learned", "list"])

        assert result.exit_code == 0
        assert "No learned data yet" in result.output


class TestClearTemplates:
    def test_every_picture_is_removed(self) -> None:
        _bank("Submit")
        _bank("Cancel")

        result = runner.invoke(app, ["learned", "clear", "--templates", "--yes"])

        assert result.exit_code == 0
        assert "2 banked element picture(s) cleared" in result.output
        assert template_store.inventory() == []

    def test_one_host_can_be_cleared_without_touching_the_others(self) -> None:
        _bank("Submit", "localhost:3000")
        _bank("Submit", "app.example.com")

        result = runner.invoke(
            app,
            ["learned", "clear", "--templates", "--host", "localhost:3000", "--yes"],
        )

        assert result.exit_code == 0
        survivors = template_store.inventory()
        assert [e.scope for e in survivors] == ["app.example.com"]

    def test_the_host_is_matched_the_way_a_run_stored_it(self) -> None:
        """``localhost:3000`` on the command line has to reach ``localhost_3000``.

        A colon is not a legal directory name on Windows, so the store rewrites
        it. If the CLI did not apply the same rewrite, ``--host`` would silently
        clear nothing and report success.
        """
        _bank("Submit", "localhost:3000")

        result = runner.invoke(
            app,
            ["learned", "clear", "--templates", "--host", "localhost:3000", "--yes"],
        )

        assert "No banked element pictures" not in result.output
        assert template_store.inventory() == []

    def test_an_empty_store_is_reported_not_cleared(self) -> None:
        result = runner.invoke(app, ["learned", "clear", "--templates", "--yes"])

        assert result.exit_code == 0
        assert "No banked element pictures" in result.output

    def test_an_empty_host_names_the_host_in_the_message(self) -> None:
        _bank("Submit", "app.example.com")

        result = runner.invoke(
            app,
            ["learned", "clear", "--templates", "--host", "other.example.com", "--yes"],
        )

        assert "No banked element pictures for other.example.com" in result.output
        assert len(template_store.inventory()) == 1

    def test_declining_the_prompt_keeps_the_pictures(self) -> None:
        _bank("Submit")

        result = runner.invoke(app, ["learned", "clear", "--templates"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        assert len(template_store.inventory()) == 1

    def test_accepting_the_prompt_removes_them(self) -> None:
        _bank("Submit")

        result = runner.invoke(app, ["learned", "clear", "--templates"], input="y\n")

        assert result.exit_code == 0
        assert template_store.inventory() == []

    def test_remembered_coordinates_survive_a_template_clear(self, _isolate_config: Path) -> None:
        """The two kinds of memory answer different questions.

        "AWT clicks the wrong place" is a coordinate; "AWT heals to the wrong
        element" is a picture. Clearing both when the user asked about one
        destroys knowledge they did not ask to lose.
        """
        from aat.learning.store import LearnedStore

        store = LearnedStore(_isolate_config / "learned.db")
        store.save_state_coords("Submit", "login", 100, 200)
        assert len(store.list_state_coords()) == 1
        _bank("Submit")

        result = runner.invoke(app, ["learned", "clear", "--templates", "--yes"])

        assert result.exit_code == 0
        assert template_store.inventory() == []
        assert len(LearnedStore(_isolate_config / "learned.db").list_state_coords()) == 1
