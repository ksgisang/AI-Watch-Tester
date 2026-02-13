"""Humanizer — Bezier mouse movement, variable typing speed.

Wraps engine mouse/keyboard calls with human-like behavior:
- Mouse: Bezier curve movement via engine.move_mouse()
- Typing: Variable delay per character via engine.type_text()
"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from aat.core.models import HumanizerConfig

if TYPE_CHECKING:
    from aat.engine.base import BaseEngine


class Humanizer:
    """Human-like mouse and keyboard interaction wrapper."""

    def __init__(self, config: HumanizerConfig | None = None) -> None:
        self._config = config or HumanizerConfig()

    async def move_to(self, engine: BaseEngine, x: int, y: int) -> None:
        """Move mouse from current position to (x, y) via Bezier curve.

        Args:
            engine: BaseEngine instance (uses duck typing to avoid circular import).
            x: Target x coordinate.
            y: Target y coordinate.
        """
        if not self._config.enabled:
            await engine.move_mouse(x, y)
            return

        # Get current mouse position from engine
        current_x, current_y = 0, 0
        if hasattr(engine, "mouse_position"):
            current_x, current_y = engine.mouse_position
        duration = random.uniform(
            self._config.mouse_speed_min,
            self._config.mouse_speed_max,
        )

        points = self._generate_bezier_points(
            start=(current_x, current_y),
            end=(x, y),
            num_control=self._config.bezier_control_points,
        )

        # Move along the curve (~60fps)
        steps = max(int(duration / 0.016), 10)
        step_delay = duration / steps
        for i in range(1, steps + 1):
            t = i / steps
            px, py = self._bezier_point(t, points)
            await engine.move_mouse(int(px), int(py))
            await asyncio.sleep(step_delay)

        # Brief pause after arrival (human hesitation before click)
        await asyncio.sleep(random.uniform(0.1, 0.3))

    async def type_text(self, engine: BaseEngine, text: str) -> None:
        """Type text one character at a time with variable delay.

        Args:
            engine: BaseEngine instance.
            text: Text to type.
        """
        if not self._config.enabled:
            await engine.type_text(text)
            return

        for char in text:
            await engine.type_text(char)
            delay = random.uniform(
                self._config.typing_delay_min,
                self._config.typing_delay_max,
            )
            await asyncio.sleep(delay)

    @staticmethod
    def _generate_bezier_points(
        start: tuple[int, int],
        end: tuple[int, int],
        num_control: int,
    ) -> list[tuple[float, float]]:
        """Generate random control points between start and end."""
        points: list[tuple[float, float]] = [(float(start[0]), float(start[1]))]
        for _ in range(num_control):
            cx = random.uniform(
                float(min(start[0], end[0])),
                float(max(start[0], end[0])),
            )
            cy = random.uniform(
                float(min(start[1], end[1])),
                float(max(start[1], end[1])),
            )
            # Add slight deviation for natural curves
            spread_x = abs(end[0] - start[0]) * 0.1 or 10.0
            spread_y = abs(end[1] - start[1]) * 0.1 or 10.0
            cx += random.gauss(0, spread_x)
            cy += random.gauss(0, spread_y)
            points.append((cx, cy))
        points.append((float(end[0]), float(end[1])))
        return points

    @staticmethod
    def _bezier_point(
        t: float,
        points: list[tuple[float, float]],
    ) -> tuple[float, float]:
        """Compute point on Bezier curve using De Casteljau's algorithm."""
        pts = list(points)
        while len(pts) > 1:
            pts = [
                (
                    (1 - t) * pts[i][0] + t * pts[i + 1][0],
                    (1 - t) * pts[i][1] + t * pts[i + 1][1],
                )
                for i in range(len(pts) - 1)
            ]
        return pts[0]
