"""Tests for aat doctor's browser-build check.

The check used to ask only whether an ``ms-playwright`` directory existed, so
any stale build earned a ✓. Upgrading Playwright leaves the old build behind:
doctor reported a healthy environment, the first run died on a missing
executable, and doctor's output was byte-identical before and after the fix.
A green light that cannot go red carries no information — so every test here
pairs a healthy case with the unhealthy one it has to distinguish.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aat.cli.commands import doctor_cmd

_DRY_RUN_OUTPUT = """\
Chrome for Testing 145.0.7632.6 (playwright chromium v1208)
  Install location:    {cache}/chromium-1208
  Download url:        https://cdn.playwright.dev/chrome-for-testing-public/x.zip

FFmpeg (playwright ffmpeg v1011)
  Install location:    {cache}/ffmpeg-1011
  Download url:        https://cdn.playwright.dev/builds/ffmpeg/1011/ffmpeg-mac.zip

Chrome Headless Shell 145.0.7632.6 (playwright chromium-headless-shell v1208)
  Install location:    {cache}/chromium_headless_shell-1208
  Download url:        https://cdn.playwright.dev/chrome-for-testing-public/y.zip
"""


class _Completed:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    d = tmp_path / "ms-playwright"
    d.mkdir()
    return d


def _stub_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    returncode: int = 0,
) -> None:
    def fake_run(*_a: Any, **_k: Any) -> _Completed:
        return _Completed(stdout, returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)


class TestRequiredBrowserBuilds:
    def test_parses_install_locations(self, monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))
        builds = doctor_cmd._required_browser_builds("chromium")
        assert builds is not None
        assert [p.name for p in builds] == [
            "chromium-1208",
            "chromium_headless_shell-1208",
        ]

    def test_ffmpeg_is_not_required(self, monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
        """AWT never records video, so a missing ffmpeg cannot break a run.

        Requiring it would raise an alarm about something harmless, which is
        the same failure as a ✓ that cannot go red — just inverted.
        """
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))
        builds = doctor_cmd._required_browser_builds("chromium")
        assert builds is not None
        assert not any("ffmpeg" in p.name for p in builds)

    def test_none_when_playwright_cannot_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Older Playwright has no --dry-run; the caller must fall back."""
        _stub_dry_run(monkeypatch, "unknown option '--dry-run'", returncode=1)
        assert doctor_cmd._required_browser_builds("chromium") is None

    def test_none_when_no_install_locations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_dry_run(monkeypatch, "nothing to install\n")
        assert doctor_cmd._required_browser_builds("chromium") is None

    def test_none_when_the_call_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_a: Any, **_k: Any) -> None:
            raise subprocess.TimeoutExpired(cmd="playwright", timeout=60)

        monkeypatch.setattr(subprocess, "run", boom)
        assert doctor_cmd._required_browser_builds("chromium") is None

    def test_asks_for_one_browser_not_all(
        self, monkeypatch: pytest.MonkeyPatch, cache: Path
    ) -> None:
        """A bare --dry-run reports firefox and webkit too.

        Requiring those would fail every chromium-only install.
        """
        seen: list[list[str]] = []

        def fake_run(cmd: list[str], **_k: Any) -> _Completed:
            seen.append(cmd)
            return _Completed(_DRY_RUN_OUTPUT.format(cache=cache))

        monkeypatch.setattr(subprocess, "run", fake_run)
        doctor_cmd._required_browser_builds("firefox")
        assert seen[0][-2:] == ["--dry-run", "firefox"]


class TestCheckBrowserBuild:
    def test_passes_when_every_required_build_is_present(
        self, monkeypatch: pytest.MonkeyPatch, cache: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (cache / "chromium-1208").mkdir()
        (cache / "chromium_headless_shell-1208").mkdir()
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))

        assert doctor_cmd._check_browser_build("chromium") is True
        out = capsys.readouterr().out
        assert "chromium-1208" in out
        assert "missing" not in out

    def test_fails_when_the_required_build_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, cache: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The defect, stated directly: a stale build must not earn a ✓."""
        (cache / "chromium-1243").mkdir()
        (cache / "chromium_headless_shell-1243").mkdir()
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))

        assert doctor_cmd._check_browser_build("chromium") is False
        out = capsys.readouterr().out
        assert "missing: chromium-1208" in out
        # Naming the build that *is* there is the line that explains why a
        # setup that worked yesterday stopped working today.
        assert "chromium-1243" in out
        assert "playwright install chromium" in out

    def test_reports_builds_from_the_directory_playwright_named(
        self, monkeypatch: pytest.MonkeyPatch, cache: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """PLAYWRIGHT_BROWSERS_PATH moves the cache.

        Listing builds from a guessed default directory would contradict the
        "missing" lines printed immediately above it.
        """
        (cache / "chromium-1243").mkdir()
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))

        doctor_cmd._check_browser_build("chromium")
        assert str(cache) in capsys.readouterr().out

    def test_partial_install_still_fails(
        self, monkeypatch: pytest.MonkeyPatch, cache: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Headless runs need the shell; snapshot and diff force headless."""
        (cache / "chromium-1208").mkdir()
        _stub_dry_run(monkeypatch, _DRY_RUN_OUTPUT.format(cache=cache))

        assert doctor_cmd._check_browser_build("chromium") is False
        assert "missing: chromium_headless_shell-1208" in capsys.readouterr().out

    def test_fallback_warns_rather_than_claiming_health(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When Playwright cannot report the build, say so instead of ✓."""
        existing = tmp_path / "ms-playwright"
        existing.mkdir()
        _stub_dry_run(monkeypatch, "", returncode=1)
        monkeypatch.setattr(doctor_cmd, "_browser_cache_dirs", lambda: [existing])

        assert doctor_cmd._check_browser_build("chromium") is True
        out = capsys.readouterr().out
        assert "cannot report the build it requires" in out
        assert "✓" not in out

    def test_fallback_fails_when_nothing_is_installed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _stub_dry_run(monkeypatch, "", returncode=1)
        monkeypatch.setattr(doctor_cmd, "_browser_cache_dirs", lambda: [tmp_path / "absent"])

        assert doctor_cmd._check_browser_build("chromium") is False
        assert "No Playwright browsers installed" in capsys.readouterr().out


class TestConfiguredBrowser:
    def test_uses_the_configured_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """doctor must check the browser the next run will actually launch."""
        from aat.core.models import Config

        cfg = Config()
        cfg.engine.browser = "firefox"
        monkeypatch.setattr(doctor_cmd, "load_config", lambda: cfg)
        assert doctor_cmd._configured_browser() == "firefox"

    def test_defaults_to_chromium_without_a_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> None:
            raise RuntimeError("no config")

        monkeypatch.setattr(doctor_cmd, "load_config", boom)
        assert doctor_cmd._configured_browser() == "chromium"


class TestTesseractLanguageCheck:
    """The green light that could not go red, again — this time for OCR.

    ``_check_tesseract`` asked only whether the binary existed. Tesseract
    installs English-only everywhere AWT documents, so a user testing a Korean
    canvas app got a ✓ from doctor and ``Text '...' not visible on page`` from
    the run, with the diagnosis blaming the page. AWT's own CI reproduced it
    exactly: the runner had ``tesseract-ocr`` without ``tesseract-ocr-kor``.
    """

    def test_missing_language_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            doctor_cmd, "_installed_tesseract_languages", lambda: {"eng", "osd"}
        )
        monkeypatch.setattr(doctor_cmd, "_configured_ocr_languages", lambda: ["eng", "kor"])
        lines: list[str] = []
        monkeypatch.setattr(doctor_cmd, "_warn", lines.append)
        monkeypatch.setattr(doctor_cmd, "_hint", lines.append)

        doctor_cmd._check_tesseract_languages()

        assert any("kor" in line for line in lines)
        assert any("not visible on page" in line for line in lines), (
            "the warning must name the symptom, or the user cannot connect it "
            "to the failure they are actually looking at"
        )

    def test_nothing_is_said_when_every_language_is_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silence is the healthy case. A warning on a correct setup is noise."""
        monkeypatch.setattr(
            doctor_cmd, "_installed_tesseract_languages", lambda: {"eng", "kor"}
        )
        monkeypatch.setattr(doctor_cmd, "_configured_ocr_languages", lambda: ["eng", "kor"])
        lines: list[str] = []
        monkeypatch.setattr(doctor_cmd, "_warn", lines.append)
        monkeypatch.setattr(doctor_cmd, "_hint", lines.append)

        doctor_cmd._check_tesseract_languages()

        assert lines == []

    def test_an_unaskable_tesseract_says_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guessing is worse than silence here.

        If ``--list-langs`` cannot be read, the packs may well be installed;
        warning anyway would send users to install something they have.
        """
        monkeypatch.setattr(doctor_cmd, "_installed_tesseract_languages", lambda: None)
        monkeypatch.setattr(doctor_cmd, "_configured_ocr_languages", lambda: ["eng", "kor"])
        lines: list[str] = []
        monkeypatch.setattr(doctor_cmd, "_warn", lines.append)
        monkeypatch.setattr(doctor_cmd, "_hint", lines.append)

        doctor_cmd._check_tesseract_languages()

        assert lines == []

    def test_language_list_is_parsed_without_its_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first line of ``--list-langs`` is prose, not a language code."""
        _stub_dry_run(monkeypatch, "List of available languages in ...:\neng\nkor\nosd\n")
        assert doctor_cmd._installed_tesseract_languages() == {"eng", "kor", "osd"}

    def test_a_configured_language_comes_from_the_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Checking a hard-coded pair would miss whatever the user set."""
        from aat.core.models import Config

        cfg = Config()
        cfg.matching.ocr_languages = ["eng", "jpn"]
        monkeypatch.setattr(doctor_cmd, "load_config", lambda: cfg)
        assert doctor_cmd._configured_ocr_languages() == ["eng", "jpn"]

    def test_the_tesseract_check_still_passes_without_the_packs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing pack is a warning, not a failure.

        English-only is a correct setup for an English-only app, and counting
        it as an issue would make ``doctor`` exit non-zero for people with
        nothing wrong.
        """
        monkeypatch.setattr(doctor_cmd.shutil, "which", lambda _n: "/usr/bin/tesseract")
        _stub_dry_run(monkeypatch, "tesseract 5.5.0\n")
        monkeypatch.setattr(
            doctor_cmd, "_installed_tesseract_languages", lambda: {"eng", "osd"}
        )
        monkeypatch.setattr(doctor_cmd, "_configured_ocr_languages", lambda: ["eng", "kor"])
        lines: list[str] = []
        monkeypatch.setattr(doctor_cmd, "_ok", lines.append)
        monkeypatch.setattr(doctor_cmd, "_warn", lines.append)
        monkeypatch.setattr(doctor_cmd, "_hint", lines.append)

        assert doctor_cmd._check_tesseract() is True
        assert any("kor" in line for line in lines), "the warning must still be printed"
