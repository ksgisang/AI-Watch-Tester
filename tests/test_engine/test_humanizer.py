"""Tests for Humanizer — Bezier mouse movement, variable typing."""

from __future__ import annotations

import pytest

from aat.core.models import HumanizerConfig
from aat.engine.humanizer import Humanizer


class MockEngine:
    """Mock engine that records mouse/keyboard calls."""

    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []
        self.typed: list[str] = []
        self.mouse_position: tuple[int, int] = (0, 0)

    async def move_mouse(self, x: int, y: int) -> None:
        self.moves.append((x, y))
        self.mouse_position = (x, y)

    async def type_text(self, text: str) -> None:
        self.typed.append(text)


class TestHumanizer:
    @pytest.mark.asyncio
    async def test_move_to_disabled(self) -> None:
        """When disabled, move_to calls engine.move_mouse directly."""
        config = HumanizerConfig(enabled=False)
        humanizer = Humanizer(config)
        engine = MockEngine()
        await humanizer.move_to(engine, 100, 200)
        assert engine.moves == [(100, 200)]

    @pytest.mark.asyncio
    async def test_move_to_enabled_generates_multiple_moves(self) -> None:
        """When enabled, move_to generates multiple intermediate moves."""
        config = HumanizerConfig(
            enabled=True,
            mouse_speed_min=0.01,
            mouse_speed_max=0.02,
        )
        humanizer = Humanizer(config)
        engine = MockEngine()
        await humanizer.move_to(engine, 500, 300)
        # Should have multiple intermediate moves (at least 10)
        assert len(engine.moves) >= 10
        # Last move should be at or near the target
        last_x, last_y = engine.moves[-1]
        assert last_x == 500
        assert last_y == 300

    @pytest.mark.asyncio
    async def test_type_text_disabled(self) -> None:
        """When disabled, type_text passes full text to engine."""
        config = HumanizerConfig(enabled=False)
        humanizer = Humanizer(config)
        engine = MockEngine()
        await humanizer.type_text(engine, "hello")
        assert engine.typed == ["hello"]

    @pytest.mark.asyncio
    async def test_type_text_enabled_types_per_char(self) -> None:
        """When enabled, type_text types one character at a time."""
        config = HumanizerConfig(
            enabled=True,
            typing_delay_min=0.001,
            typing_delay_max=0.002,
        )
        humanizer = Humanizer(config)
        engine = MockEngine()
        await humanizer.type_text(engine, "hi")
        assert engine.typed == ["h", "i"]

    @pytest.mark.asyncio
    async def test_default_config(self) -> None:
        humanizer = Humanizer()
        assert humanizer._config.enabled is True
        assert humanizer._config.mouse_speed_min == 0.1

    def test_bezier_point_endpoints(self) -> None:
        """Bezier curve starts at t=0 and ends at t=1."""
        points = [(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)]
        start = Humanizer._bezier_point(0.0, points)
        end = Humanizer._bezier_point(1.0, points)
        assert start == (0.0, 0.0)
        assert end == (100.0, 0.0)

    def test_generate_bezier_points_count(self) -> None:
        """Generated points = start + control points + end."""
        points = Humanizer._generate_bezier_points(start=(0, 0), end=(100, 100), num_control=3)
        assert len(points) == 5  # 1 start + 3 control + 1 end
        assert points[0] == (0.0, 0.0)
        assert points[-1] == (100.0, 100.0)


class TestHumanizerScreenCoords:
    """Tests for move_to_screen (screen coordinate Bezier movement)."""

    @pytest.mark.asyncio
    async def test_move_to_screen_disabled(self) -> None:
        config = HumanizerConfig(enabled=False)
        humanizer = Humanizer(config)
        engine = MockEngine()
        engine.move_mouse_screen = engine.move_mouse  # type: ignore[attr-defined]
        await humanizer.move_to_screen(engine, 400, 500)  # type: ignore[arg-type]
        assert engine.moves == [(400, 500)]

    @pytest.mark.asyncio
    async def test_move_to_screen_enabled(self) -> None:
        from unittest.mock import MagicMock

        config = HumanizerConfig(
            enabled=True, mouse_speed_min=0.01, mouse_speed_max=0.02,
        )
        humanizer = Humanizer(config)
        engine = MockEngine()
        engine.move_mouse_screen = engine.move_mouse  # type: ignore[attr-defined]
        engine.pag = MagicMock()  # type: ignore[attr-defined]
        engine.pag.position.return_value = MagicMock(x=0, y=0)
        await humanizer.move_to_screen(engine, 500, 300)  # type: ignore[arg-type]
        assert len(engine.moves) >= 10
        last_x, last_y = engine.moves[-1]
        assert last_x == 500
        assert last_y == 300
