"""aat doctor — environment health check."""

from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from aat.core.config import load_config

if TYPE_CHECKING:
    from aat.core.models import Config

_IS_MAC = platform.system() == "Darwin"
_IS_LINUX = platform.system() == "Linux"
_IS_WIN = platform.system() == "Windows"


def _ok(msg: str) -> None:
    typer.echo(f"  {typer.style('✓', fg=typer.colors.GREEN)} {msg}")


def _warn(msg: str) -> None:
    typer.echo(f"  {typer.style('!', fg=typer.colors.YELLOW)} {msg}")


def _fail(msg: str) -> None:
    typer.echo(f"  {typer.style('✗', fg=typer.colors.RED)} {msg}")


def _hint(msg: str) -> None:
    typer.echo(f"    → {typer.style(msg, fg=typer.colors.CYAN)}")


def _check_python() -> bool:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 11):
        _ok(f"Python {version_str}")
        return True
    _fail(f"Python {version_str} — requires 3.11+")
    if _IS_MAC:
        _hint("brew install python@3.12")
        _hint("pipx install aat-devqa --python python3.12")
    elif _IS_LINUX:
        _hint("sudo apt install python3.12 python3.12-venv")
        _hint("pipx install aat-devqa --python python3.12")
    elif _IS_WIN:
        _hint("winget install Python.Python.3.12")
        _hint("pipx install aat-devqa")
    else:
        _hint("https://www.python.org/downloads/")
    return False


def _check_aat_cli() -> bool:
    try:
        from aat import __version__

        _ok(f"AWT CLI v{__version__}")
        return True
    except ImportError:
        _fail("AWT CLI not installed")
        _hint("pip install aat-devqa")
        return False


def _playwright_version() -> str:
    try:
        from importlib.metadata import version

        return version("playwright")
    except Exception:
        return "unknown"


def _configured_browser() -> str:
    """Which browser the next run will actually launch."""
    try:
        return load_config().engine.browser or "chromium"
    except Exception:
        return "chromium"


def _required_browser_builds(browser: str) -> list[Path] | None:
    """Ask Playwright which browser builds it needs, by absolute path.

    ``playwright install --dry-run <browser>`` prints an "Install location:"
    line per required build, each ending in a build number such as
    ``chromium-1243``. That number is pinned to the installed Playwright
    version, so it is the only thing worth comparing against the disk.

    Returns ``None`` when Playwright cannot tell us -- older releases have no
    ``--dry-run`` -- so the caller can fall back and say that it fell back.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", browser],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None

    builds = [
        Path(line.split("Install location:", 1)[1].strip())
        for line in proc.stdout.splitlines()
        if "Install location:" in line
    ]
    # ffmpeg is for video recording, which AWT never asks for. Requiring it
    # would raise an alarm about something that cannot break a test run.
    builds = [p for p in builds if "ffmpeg" not in p.name]
    return builds or None


def _browser_cache_dirs() -> list[Path]:
    dirs = [Path.home() / ".cache" / "ms-playwright"]
    if not _IS_WIN:
        dirs.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    return dirs


def _check_browser_build(browser: str) -> bool:
    """Compare the installed builds against the build Playwright requires.

    The old check asked only whether an ``ms-playwright`` directory existed,
    so any stale build earned a ✓. Upgrading Playwright leaves the old build
    in place: doctor reported a healthy environment and the first run then
    died on a missing executable, with identical doctor output before and
    after the fix. A green light that cannot go red carries no information.
    """
    pw_version = _playwright_version()
    required = _required_browser_builds(browser)

    if required is None:
        # Last resort: the directory check, named as the guess it is.
        if any(d.exists() for d in _browser_cache_dirs()):
            _warn(
                f"{browser} directory found, but this Playwright ({pw_version}) "
                "cannot report the build it requires"
            )
            _hint(f"playwright install {browser}  # run it anyway to be sure")
            return True
        _fail(f"No Playwright browsers installed for {browser}")
        _hint(f"playwright install {browser}")
        return False

    missing = [p for p in required if not p.exists()]
    if not missing:
        names = ", ".join(p.name for p in required)
        _ok(f"{browser} build {names} — matches Playwright {pw_version}")
        return True

    _fail(f"{browser} build required by Playwright {pw_version} is missing")
    for p in missing:
        _hint(f"missing: {p.name}")
    # Name what *is* there. After a Playwright upgrade this is the whole
    # story, and it is the line that tells the user why a working setup broke.
    # Look in the directory Playwright itself named, not in a guessed one --
    # PLAYWRIGHT_BROWSERS_PATH moves the cache, and reporting builds from
    # somewhere else would contradict the "missing" lines above.
    cache = missing[0].parent
    stem = missing[0].name.split("-")[0]
    if cache.exists():
        found = sorted(d.name for d in cache.iterdir() if d.name.startswith(f"{stem}-"))
        if found:
            _hint(f"found instead, in {cache}: {', '.join(found)}")
    _hint(f"playwright install {browser}")
    return False


def _check_playwright(browser: str = "chromium") -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        _fail("Playwright not installed")
        _hint(f"pip install playwright && playwright install {browser}")
        return False

    _ok(f"Playwright {_playwright_version()} installed")
    return _check_browser_build(browser)


def _configured_ocr_languages() -> list[str]:
    """Which language packs the next run will ask Tesseract for."""
    try:
        return list(load_config().matching.ocr_languages)
    except Exception:
        return ["eng", "kor"]


def _installed_tesseract_languages() -> set[str] | None:
    """What ``tesseract --list-langs`` reports, or None if it cannot be asked."""
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None

    # First line is a header ("List of available languages..."); the rest are
    # one code per line. Older builds print the list on stderr.
    text = result.stdout or result.stderr or ""
    lines = [line.strip() for line in text.splitlines()[1:]]
    found = {line for line in lines if line and " " not in line}
    return found or None


def _check_tesseract_languages() -> None:
    """Warn when a configured language has no traineddata on this machine.

    Tesseract installs with English only on every platform we document, and a
    missing pack is not an error you can see: ``image_to_string`` raises, the
    OCR fallback catches it, and the step reports the text as not visible. The
    page is fine, the assertion is fine, and the diagnosis blames the page.

    This is not hypothetical -- AWT's own CI reproduced it. The runner installed
    ``tesseract-ocr`` without ``tesseract-ocr-kor``, and the five tests that
    prove the Korean OCR fallback works failed with "not visible on page", the
    same sentence a user would get. ``doctor`` said Tesseract was fine, because
    it only asked whether the binary existed.

    A warning, not a failure: English-only is a correct setup for an
    English-only app, and a red light there would be noise.
    """
    configured = _configured_ocr_languages()
    installed = _installed_tesseract_languages()
    if installed is None:
        return

    missing = [lang for lang in configured if lang not in installed]
    if not missing:
        return

    _warn(
        f"Tesseract has no data for: {', '.join(missing)} "
        "(configured in matching.ocr_languages)"
    )
    _hint("Without it, canvas text in that language reads as 'not visible on page'")
    if _IS_MAC:
        _hint("brew install tesseract-lang")
    elif _IS_LINUX:
        _hint(f"sudo apt install {' '.join(f'tesseract-ocr-{lang}' for lang in missing)}")
    else:
        _hint("Install the language data: https://github.com/tesseract-ocr/tessdata")


def _check_tesseract() -> bool:
    tess = shutil.which("tesseract")
    if tess:
        try:
            result = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.split("\n")[0] if result.stdout else "unknown"
            _ok(f"Tesseract OCR — {version}")
        except Exception:
            _ok("Tesseract OCR found")
        _check_tesseract_languages()
        return True

    _fail("Tesseract OCR not found")
    if _IS_MAC:
        _hint("brew install tesseract")
    elif _IS_LINUX:
        _hint("sudo apt install tesseract-ocr tesseract-ocr-kor")
    elif _IS_WIN:
        _hint(
            "choco install tesseract OR download from https://github.com/UB-Mannheim/tesseract/wiki"
        )
    else:
        _hint("Install Tesseract: https://tesseract-ocr.github.io/tessdoc/Installation.html")
    return False


def _check_opencv() -> bool:
    try:
        import cv2

        _ok(f"OpenCV {cv2.__version__}")
        return True
    except ImportError:
        _fail("OpenCV not installed")
        _hint("pip install opencv-python-headless")
        return False


def _check_config() -> tuple[bool, Config | None]:
    try:
        config = load_config()
        config_path = Path.cwd() / "aat.config.yaml"
        if config_path.exists():
            _ok(f"Config: {config_path}")
        else:
            _warn("No aat.config.yaml in current directory")
            _hint("Run: aat init --name my-project --url https://mysite.com")
        return True, config
    except Exception:
        _warn("No valid config found")
        _hint("Run: aat init --name my-project --url https://mysite.com")
        return False, None


def _check_ai_provider(config: Config | None) -> bool:
    if config is None:
        _warn("AI Provider — skipped (no config)")
        return False

    provider = config.ai.provider
    api_key = config.ai.api_key
    model = config.ai.model

    if provider == "ollama":
        _ok(f"AI Provider: {provider} ({model}) — free, offline")
        # Test connection
        try:
            from aat.core.connection import test_ai_connection

            success, msg = asyncio.run(test_ai_connection(config.ai))
            if success:
                _ok(f"  Connection: {msg}")
            else:
                _warn(f"  Connection: {msg}")
        except Exception as e:
            _warn(f"  Connection test failed: {e}")
        return True

    if not api_key:
        _fail(f"AI Provider: {provider} — API key not set")
        _hint("Run: aat setup")
        return False

    _ok(f"AI Provider: {provider} ({model})")
    key_preview = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    _ok(f"  API Key: {key_preview}")

    # Test connection
    try:
        from aat.core.connection import test_ai_connection

        success, msg = asyncio.run(test_ai_connection(config.ai))
        if success:
            _ok(f"  Connection: {msg}")
        else:
            _fail(f"  Connection: {msg}")
            return False
    except Exception as e:
        _warn(f"  Connection test failed: {e}")

    return True


def doctor_command(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    skip_connection: bool = typer.Option(
        False, "--skip-connection", help="Skip AI connection test."
    ),
) -> None:
    """Check system environment and dependencies."""
    typer.echo()
    typer.echo(typer.style("  AWT Doctor — Environment Check", bold=True))
    typer.echo("  " + "=" * 40)
    typer.echo()

    issues = 0

    # 1. Python
    if not _check_python():
        issues += 1

    # 2. AWT CLI
    if not _check_aat_cli():
        issues += 1

    # 3. Playwright — against the browser the next run will actually launch
    if not _check_playwright(_configured_browser()):
        issues += 1

    # 4. Tesseract OCR
    if not _check_tesseract():
        issues += 1

    # 5. OpenCV
    if not _check_opencv():
        issues += 1

    # 6. Config
    typer.echo()
    has_config, config = _check_config()

    # 7. AI Provider
    if not skip_connection and not _check_ai_provider(config):
        issues += 1

    # Summary
    typer.echo()
    typer.echo("  " + "-" * 40)
    if issues == 0:
        typer.echo(
            typer.style("  All checks passed! Ready to test.", fg=typer.colors.GREEN, bold=True)
        )
    else:
        typer.echo(
            typer.style(
                f"  {issues} issue(s) found. Fix the items above.",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
    typer.echo()
