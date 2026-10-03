"""Tests for the banked-element-picture store.

Two defects are pinned here, because both let the store lie:

* **Cross-application collisions.** The key used to be ``md5(target_name)``
  with no notion of site, so a picture of "확인" banked against one app was
  the picture a different app's lookup got back. That is a wrong click that
  *passes*, which is the one outcome AAT-109 says must never happen.
* **Cropping the wrong rectangle.** ``bounding_box()`` reports CSS pixels; a
  retina screenshot is twice as wide. Cropping CSS coordinates out of a 2x
  image banks the element's top-left quarter, and a quarter of a button is a
  template that matches nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from aat.matchers import template_store

# ─── Helpers ─────────────────────────────────────────────────


def _png(width: int, height: int, shade: int = 30) -> bytes:
    img = np.full((height, width, 3), shade, dtype=np.uint8)
    return bytes(cv2.imencode(".png", img)[1])


def _png_with_patch(
    width: int,
    height: int,
    *,
    box: tuple[int, int, int, int],
    colour: tuple[int, int, int] = (0, 0, 255),
) -> bytes:
    """A dark image with one solid rectangle, so a crop can be identified."""
    img = np.full((height, width, 3), 30, dtype=np.uint8)
    x, y, w, h = box
    img[y : y + h, x : x + w] = colour
    return bytes(cv2.imencode(".png", img)[1])


def _bank(
    target: str = "Submit",
    scope: str = "example.com",
    *,
    screenshot: bytes | None = None,
    left: float = 40,
    top: float = 50,
    width: float = 80,
    height: float = 30,
    viewport_width: int | None = None,
) -> Path | None:
    return template_store.save(
        scope,
        target,
        screenshot if screenshot is not None else _png(320, 240),
        left=left,
        top=top,
        width=width,
        height=height,
        method="playwright",
        confidence=0.9,
        viewport_width=viewport_width,
    )


def _backdate(path: Path, days: float) -> None:
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["saved_at"] = time.time() - days * 86400
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


# ─── Where the store lives ───────────────────────────────────


class TestLocation:
    def test_env_var_relocates_the_store(self) -> None:
        """The autouse fixture in conftest relies on this being read per call."""
        assert template_store.templates_root() != Path.home() / ".awt" / "templates"

    def test_save_writes_under_the_override(self, _isolate_template_store: Path) -> None:
        png = _bank()

        assert png is not None
        assert _isolate_template_store in png.parents


# ─── Scoping ─────────────────────────────────────────────────


class TestScoping:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://app.example.com/login", "app.example.com"),
            # The port survives as part of the name, but not as a colon: a
            # scope is a directory, and ``localhost:3000`` is not a legal
            # directory name on Windows.
            ("http://localhost:3000/", "localhost_3000"),
            ("https://APP.Example.COM/x", "app.example.com"),
        ],
    )
    def test_host_and_port_identify_the_application(self, url: str, expected: str) -> None:
        assert template_store.scope_for(url) == expected

    def test_two_ports_on_localhost_are_two_applications(self) -> None:
        """Routinely true on a developer's machine, and the whole point of scoping."""
        assert template_store.scope_for("http://localhost:3000/") != template_store.scope_for(
            "http://localhost:8080/"
        )

    @pytest.mark.parametrize("url", [None, "", "about:blank", "file:///tmp/page.html"])
    def test_pages_without_a_host_fall_into_one_bucket(self, url: str | None) -> None:
        assert template_store.scope_for(url) == template_store.UNSCOPED

    def test_path_separators_cannot_escape_the_store(self) -> None:
        """A scope becomes a directory name, so it must not contain a path."""
        scope = template_store.scope_for_host("../../etc")

        assert "/" not in scope
        assert ".." not in scope.strip(".")

    def test_cli_host_matches_the_scope_a_run_wrote(self) -> None:
        """`aat learned clear --host localhost:3000` has to hit what a run banked."""
        assert template_store.scope_for_host("localhost:3000") == template_store.scope_for(
            "http://localhost:3000/dashboard"
        )

    def test_same_target_on_two_hosts_does_not_collide(self) -> None:
        a = _bank("확인", scope="a.example.com")
        b = _bank("확인", scope="b.example.com")

        assert a is not None
        assert b is not None
        assert a != b
        assert a.exists()
        assert b.exists()

    def test_a_lookup_never_crosses_hosts(self) -> None:
        _bank("확인", scope="a.example.com")

        assert template_store.lookup("a.example.com", "확인") is not None
        assert template_store.lookup("b.example.com", "확인") is None


# ─── Saving ──────────────────────────────────────────────────


class TestSave:
    def test_round_trip(self) -> None:
        png = _bank("Submit")

        assert png is not None
        assert template_store.lookup("example.com", "Submit") == png

    def test_crop_covers_the_element_plus_padding(self) -> None:
        png = _bank(left=40, top=50, width=80, height=30)

        assert png is not None
        img = cv2.imread(str(png))
        pad = template_store.PAD
        assert img.shape[1] == 80 + 2 * pad
        assert img.shape[0] == 30 + 2 * pad

    def test_metadata_describes_what_was_banked(self) -> None:
        png = _bank("Submit")

        assert png is not None
        meta = json.loads(png.with_suffix(".json").read_text(encoding="utf-8"))
        assert meta["target"] == "Submit"
        assert meta["method"] == "playwright"
        assert meta["confidence"] == pytest.approx(0.9)
        assert meta["saved_at"] > 0

    def test_retina_screenshot_is_scaled_before_cropping(self) -> None:
        """The failure this prevents: banking the top-left quarter of a button.

        The element sits at CSS (40,50) 80x30. At DSF 2 its pixels are at
        (80,100) 160x60. Cropping the CSS rectangle out of the 2x image would
        pick up background, so the crop is checked for the element's colour.
        """
        shot = _png_with_patch(640, 480, box=(80, 100, 160, 60))

        png = _bank(
            screenshot=shot,
            left=40,
            top=50,
            width=80,
            height=30,
            viewport_width=320,
        )

        assert png is not None
        img = cv2.imread(str(png))
        centre = img[img.shape[0] // 2, img.shape[1] // 2]
        assert tuple(int(c) for c in centre) == (0, 0, 255)
        assert img.shape[1] == 160 + 2 * template_store.PAD

    def test_an_implausible_scale_falls_back_to_one_to_one(self) -> None:
        """A full-page capture is not a scaled viewport; guessing would crop wrong."""
        shot = _png_with_patch(320, 4000, box=(40, 50, 80, 30))

        png = _bank(screenshot=shot, viewport_width=20)

        assert png is not None
        img = cv2.imread(str(png))
        assert img.shape[1] == 80 + 2 * template_store.PAD

    def test_crop_is_clamped_to_the_screenshot(self) -> None:
        """An element flush against the edge still banks, without padding off-image."""
        png = _bank(left=0, top=0, width=60, height=40, screenshot=_png(320, 240))

        assert png is not None
        img = cv2.imread(str(png))
        assert img.shape[1] == 60 + template_store.PAD
        assert img.shape[0] == 40 + template_store.PAD

    @pytest.mark.parametrize(("width", "height"), [(0, 30), (80, 0), (-10, 30)])
    def test_an_empty_rectangle_banks_nothing(self, width: float, height: float) -> None:
        assert _bank(width=width, height=height) is None

    def test_a_sliver_too_small_to_match_banks_nothing(self) -> None:
        assert _bank(width=2, height=2, left=0, top=0) is None

    def test_an_unnamed_target_banks_nothing(self) -> None:
        assert _bank("") is None

    def test_an_offscreen_element_banks_nothing(self) -> None:
        assert _bank(left=5000, top=5000) is None

    def test_corrupt_screenshot_bytes_do_not_raise(self) -> None:
        """A step that found its element must not fail on the bookkeeping after."""
        assert _bank(screenshot=b"not a png") is None

    def test_re_banking_the_same_target_replaces_it(self) -> None:
        first = _bank("Submit", width=80, height=30)
        second = _bank("Submit", width=120, height=50)

        assert first == second
        assert len(template_store.inventory("example.com")) == 1
        img = cv2.imread(str(second))
        assert img.shape[1] == 120 + 2 * template_store.PAD


# ─── Expiry ──────────────────────────────────────────────────


class TestExpiry:
    def test_a_stale_template_is_not_offered(self) -> None:
        png = _bank("Submit")
        assert png is not None
        _backdate(png, template_store.MAX_AGE_DAYS + 1)

        assert template_store.lookup("example.com", "Submit") is None

    def test_a_stale_template_is_not_deleted_by_a_lookup(self) -> None:
        """Reading is on a failing step's hot path; deleting belongs to prune."""
        png = _bank("Submit")
        assert png is not None
        _backdate(png, template_store.MAX_AGE_DAYS + 1)

        template_store.lookup("example.com", "Submit")

        assert png.exists()

    def test_a_fresh_template_is_offered(self) -> None:
        png = _bank("Submit")
        assert png is not None
        _backdate(png, template_store.MAX_AGE_DAYS - 1)

        assert template_store.lookup("example.com", "Submit") == png

    def test_a_missing_target_looks_up_to_nothing(self) -> None:
        assert template_store.lookup("example.com", "Never Seen") is None

    def test_an_empty_target_name_looks_up_to_nothing(self) -> None:
        assert template_store.lookup("example.com", "") is None


# ─── Inventory and cleanup ───────────────────────────────────


class TestInventory:
    def test_empty_store_reports_nothing(self) -> None:
        assert template_store.inventory() == []

    def test_entries_carry_their_metadata(self) -> None:
        _bank("Submit", scope="example.com", width=80, height=30)

        (entry,) = template_store.inventory()

        assert entry.scope == "example.com"
        assert entry.target == "Submit"
        assert entry.method == "playwright"
        assert entry.width == 80 + 2 * template_store.PAD
        assert entry.age_days < 1

    def test_newest_first(self) -> None:
        old = _bank("Old")
        _bank("New")
        assert old is not None
        _backdate(old, 5)

        targets = [e.target for e in template_store.inventory()]

        assert targets == ["New", "Old"]

    def test_scoped_inventory_sees_one_host(self) -> None:
        _bank("A", scope="a.example.com")
        _bank("B", scope="b.example.com")

        assert [e.target for e in template_store.inventory("a.example.com")] == ["A"]
        assert len(template_store.inventory()) == 2

    def test_an_entry_without_metadata_still_lists(self) -> None:
        """Half-written entries must be visible, or they cannot be cleaned up."""
        png = _bank("Submit")
        assert png is not None
        png.with_suffix(".json").unlink()

        (entry,) = template_store.inventory()

        assert entry.target == "?"
        assert entry.saved_at == 0.0


class TestPrune:
    def test_stale_entries_go(self) -> None:
        stale = _bank("Old")
        fresh = _bank("New")
        assert stale is not None
        assert fresh is not None
        _backdate(stale, template_store.MAX_AGE_DAYS + 2)

        removed = template_store.prune()

        assert removed == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_surplus_entries_go_oldest_first(self) -> None:
        kept = _bank("Keep")
        dropped = _bank("Drop")
        assert kept is not None
        assert dropped is not None
        _backdate(dropped, 3)

        removed = template_store.prune(max_per_scope=1)

        assert removed == 1
        assert kept.exists()
        assert not dropped.exists()

    def test_metadata_goes_with_the_picture(self) -> None:
        png = _bank("Old")
        assert png is not None
        _backdate(png, template_store.MAX_AGE_DAYS + 2)

        template_store.prune()

        assert not png.with_suffix(".json").exists()

    def test_the_cap_is_applied_per_host(self) -> None:
        a = _bank("A", scope="a.example.com")
        b = _bank("B", scope="b.example.com")
        assert a is not None
        assert b is not None

        assert template_store.prune(max_per_scope=1) == 0
        assert a.exists()
        assert b.exists()

    def test_saving_bounds_the_store_without_a_run_level_hook(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every entry point builds its own executor, so the cap lives in save()."""
        monkeypatch.setattr(template_store, "MAX_PER_SCOPE", 2)

        for i in range(5):
            png = _bank(f"Target {i}")
            assert png is not None
            # Distinct dates, so "oldest first" has something to order by.
            _backdate(png, 5 - i)

        assert len(template_store.inventory("example.com")) <= 2


class TestClear:
    def test_clears_everything(self) -> None:
        _bank("A", scope="a.example.com")
        _bank("B", scope="b.example.com")

        removed = template_store.clear()

        assert removed == 2
        assert template_store.inventory() == []

    def test_clears_one_host_only(self) -> None:
        _bank("A", scope="a.example.com")
        kept = _bank("B", scope="b.example.com")
        assert kept is not None

        removed = template_store.clear("a.example.com")

        assert removed == 1
        assert kept.exists()

    def test_legacy_sidecars_do_not_survive_a_clear(self) -> None:
        """Pre-scoping entries wrote a .txt; leaving it reports success on litter."""
        png = _bank("Submit")
        assert png is not None
        legacy = png.with_suffix(".txt")
        legacy.write_text("Submit", encoding="utf-8")

        template_store.clear()

        assert not legacy.exists()

    def test_clearing_an_empty_store_is_not_an_error(self) -> None:
        assert template_store.clear() == 0
