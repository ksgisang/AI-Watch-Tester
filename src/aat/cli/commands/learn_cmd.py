"""aat learn — design guide image learning."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path  # noqa: TC003

import typer

from aat.core.config import load_config

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})

learn_app = typer.Typer(
    name="learn",
    help="Learning data management.",
    no_args_is_help=True,
)


def _collect_images(path: Path) -> list[Path]:
    """Collect image files from a path (file or directory).

    Args:
        path: Single image file or directory to scan.

    Returns:
        List of image file paths.
    """
    if path.is_file():
        if path.suffix.lower() in _IMAGE_EXTENSIONS:
            return [path]
        return []

    images: list[Path] = []
    for ext in sorted(_IMAGE_EXTENSIONS):
        images.extend(sorted(path.glob(f"*{ext}")))
    return images


def _file_hash(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    hasher = hashlib.sha256()
    data = file_path.read_bytes()
    hasher.update(data)
    return hasher.hexdigest()


@learn_app.command("add")
def learn_add(
    path: str = typer.Argument(..., help="Image file or directory to learn from"),
    name: str | None = typer.Option(None, "--name", "-n", help="Target name"),
) -> None:
    """Register design guide images for learning."""
    source = Path(path)
    if not source.exists():
        typer.echo(
            typer.style(f"Path does not exist: {path}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    # Collect image files
    images = _collect_images(source)
    if not images:
        typer.echo(
            typer.style(
                f"No image files (.png, .jpg, .jpeg) found: {path}",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(code=1)

    # Load config to resolve directories
    config = load_config()
    assets_dir = Path(config.assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(config.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Try to use LearnedStore; fall back to simple echo if not available yet
    store = _get_store(data_dir / "learned.db")

    registered = 0
    for img_path in images:
        target_name = name or img_path.stem
        dest = assets_dir / img_path.name

        # Copy image to assets/
        if dest != img_path.resolve():
            shutil.copy2(img_path, dest)

        img_hash = _file_hash(img_path)

        if store is not None:
            _save_to_store(store, target_name, img_hash, str(dest))
        else:
            typer.echo(f"  [echo] Registered: {target_name} -> {dest}")

        registered += 1

    status = typer.style(str(registered), fg=typer.colors.GREEN)
    typer.echo(f"Registered {status} image(s) for learning.")


def _get_store(db_path: Path) -> object | None:
    """Try to create a LearnedStore instance.

    Returns None if the module is not yet available.
    """
    try:
        from aat.learning.store import LearnedStore

        return LearnedStore(db_path)
    except (ImportError, AttributeError):
        return None


def _save_to_store(store: object, target_name: str, img_hash: str, dest: str) -> None:
    """Save a LearnedElement via store.save().

    Gracefully degrades if the store API doesn't match expectations yet.
    """
    try:
        from aat.core.models import LearnedElement

        element = LearnedElement(
            scenario_id="manual",
            step_number=1,
            target_name=target_name,
            screenshot_hash=img_hash,
            correct_x=0,
            correct_y=0,
            cropped_image_path=dest,
            confidence=1.0,
        )
        store.save(element)  # type: ignore[attr-defined]
    except (ImportError, AttributeError, TypeError):
        pass
