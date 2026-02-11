"""Tests for aat learn command."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


def test_learn_help_shows_add() -> None:
    """aat learn --help shows the 'add' subcommand."""
    result = runner.invoke(app, ["learn", "--help"])
    assert result.exit_code == 0
    assert "add" in result.output


def test_learn_add_nonexistent_path() -> None:
    """aat learn add with nonexistent path exits with error."""
    result = runner.invoke(app, ["learn", "add", "/nonexistent/path/image.png"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_learn_add_no_images_in_dir(tmp_path: Path) -> None:
    """aat learn add with directory containing no images exits with error."""
    # Create a directory with non-image files
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config:
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(tmp_path / "assets")
        mock_cfg.data_dir = str(tmp_path / ".aat")
        mock_config.return_value = mock_cfg

        result = runner.invoke(app, ["learn", "add", str(tmp_path)])
        assert result.exit_code == 1
        assert "No image files" in result.output


def test_learn_add_single_file(tmp_path: Path) -> None:
    """aat learn add with a single image file registers it."""
    # Create a dummy PNG file
    img_file = tmp_path / "button.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / ".aat"

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config, \
         patch("aat.cli.commands.learn_cmd._get_store", return_value=None):
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(assets_dir)
        mock_cfg.data_dir = str(data_dir)
        mock_config.return_value = mock_cfg

        result = runner.invoke(app, ["learn", "add", str(img_file)])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "1" in result.output


def test_learn_add_directory_with_images(tmp_path: Path) -> None:
    """aat learn add with a directory scans for images."""
    # Create dummy image files
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    (tmp_path / "icon.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
    (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / ".aat"

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config, \
         patch("aat.cli.commands.learn_cmd._get_store", return_value=None):
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(assets_dir)
        mock_cfg.data_dir = str(data_dir)
        mock_config.return_value = mock_cfg

        result = runner.invoke(app, ["learn", "add", str(tmp_path)])
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "2" in result.output


def test_learn_add_with_name_option(tmp_path: Path) -> None:
    """aat learn add --name sets the target name."""
    img_file = tmp_path / "screenshot.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / ".aat"

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config, \
         patch("aat.cli.commands.learn_cmd._get_store", return_value=None):
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(assets_dir)
        mock_cfg.data_dir = str(data_dir)
        mock_config.return_value = mock_cfg

        result = runner.invoke(
            app, ["learn", "add", str(img_file), "--name", "login_button"]
        )
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "login_button" in result.output


def test_learn_add_copies_to_assets(tmp_path: Path) -> None:
    """aat learn add copies images to the assets directory."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    img_file = source_dir / "widget.png"
    img_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    img_file.write_bytes(img_content)

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / ".aat"

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config, \
         patch("aat.cli.commands.learn_cmd._get_store", return_value=None):
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(assets_dir)
        mock_cfg.data_dir = str(data_dir)
        mock_config.return_value = mock_cfg

        result = runner.invoke(app, ["learn", "add", str(img_file)])
        assert result.exit_code == 0

        # Check file was copied to assets
        copied = assets_dir / "widget.png"
        assert copied.exists()
        assert copied.read_bytes() == img_content


def test_learn_add_with_store(tmp_path: Path) -> None:
    """aat learn add uses LearnedStore when available."""
    img_file = tmp_path / "element.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    assets_dir = tmp_path / "assets"
    data_dir = tmp_path / ".aat"

    mock_store = MagicMock()

    with patch("aat.cli.commands.learn_cmd.load_config") as mock_config, \
         patch("aat.cli.commands.learn_cmd._get_store", return_value=mock_store), \
         patch("aat.cli.commands.learn_cmd._save_to_store") as mock_save:
        mock_cfg = MagicMock()
        mock_cfg.assets_dir = str(assets_dir)
        mock_cfg.data_dir = str(data_dir)
        mock_config.return_value = mock_cfg

        result = runner.invoke(app, ["learn", "add", str(img_file)])
        assert result.exit_code == 0
        assert mock_save.called
