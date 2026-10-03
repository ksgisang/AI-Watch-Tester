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
