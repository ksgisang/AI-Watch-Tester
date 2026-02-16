"""Tests for ABC interfaces — verify contracts and prevent direct instantiation."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from aat.adapters.base import AIAdapter
from aat.core.models import (
    LoopResult,
    MatchResult,
    TargetSpec,
    TestResult,
)
from aat.engine.base import BaseEngine
from aat.matchers.base import BaseMatcher
from aat.parsers.base import BaseParser
from aat.reporters.base import BaseReporter

# ── BaseEngine ──


class TestBaseEngine:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BaseEngine()  # type: ignore[abstract]

    def test_has_all_abstract_methods(self) -> None:
        expected = {
            "start",
            "stop",
            "screenshot",
            "click",
            "double_click",
            "right_click",
            "type_text",
            "press_key",
            "key_combo",
            "navigate",
            "go_back",
            "refresh",
            "scroll",
            "move_mouse",
            "get_url",
            "get_page_text",
            "save_screenshot",
        }
        assert expected == BaseEngine.__abstractmethods__

    def test_concrete_impl_works(self) -> None:
        class DummyEngine(BaseEngine):
            async def start(self) -> None: ...
            async def stop(self) -> None: ...
            async def screenshot(self) -> bytes:
                return b""

            async def click(self, x: int, y: int) -> None: ...
            async def double_click(self, x: int, y: int) -> None: ...
            async def right_click(self, x: int, y: int) -> None: ...
            async def type_text(self, text: str) -> None: ...
            async def press_key(self, key: str) -> None: ...
            async def key_combo(self, *keys: str) -> None: ...
            async def navigate(self, url: str) -> None: ...
            async def go_back(self) -> None: ...
            async def refresh(self) -> None: ...
            async def scroll(self, x: int, y: int, delta: int) -> None: ...
            async def move_mouse(self, x: int, y: int) -> None: ...
            async def get_url(self) -> str:
                return ""

            async def get_page_text(self) -> str:
                return ""

            async def save_screenshot(self, path: Path) -> Path:
                return path

        engine = DummyEngine()
        assert isinstance(engine, BaseEngine)


# ── BaseMatcher ──


class TestBaseMatcher:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BaseMatcher()  # type: ignore[abstract]

    def test_has_all_abstract_methods(self) -> None:
        expected = {"name", "find", "can_handle"}
        assert expected == BaseMatcher.__abstractmethods__

    def test_concrete_impl_works(self) -> None:
        class DummyMatcher(BaseMatcher):
            @property
            def name(self) -> str:
                return "dummy"

            async def find(self, target: TargetSpec, screenshot: bytes) -> MatchResult | None:
                return None

            def can_handle(self, target: TargetSpec) -> bool:
                return True

        matcher = DummyMatcher()
        assert isinstance(matcher, BaseMatcher)
        assert matcher.name == "dummy"
        assert matcher.can_handle(TargetSpec(text="hello"))


# ── AIAdapter ──


class TestAIAdapter:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            AIAdapter()  # type: ignore[abstract]

    def test_has_all_abstract_methods(self) -> None:
        expected = {
            "analyze_failure",
            "generate_fix",
            "generate_scenarios",
            "analyze_document",
        }
        assert expected == AIAdapter.__abstractmethods__


# ── BaseParser ──


class TestBaseParser:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BaseParser()  # type: ignore[abstract]

    def test_has_all_abstract_methods(self) -> None:
        expected = {"parse", "supported_extensions"}
        assert expected == BaseParser.__abstractmethods__

    def test_concrete_impl_works(self) -> None:
        class DummyParser(BaseParser):
            async def parse(self, file_path: Path) -> tuple[str, list[bytes]]:
                return ("text", [])

            @property
            def supported_extensions(self) -> list[str]:
                return [".md"]

        parser = DummyParser()
        assert isinstance(parser, BaseParser)
        assert parser.supported_extensions == [".md"]


# ── BaseReporter ──


class TestBaseReporter:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BaseReporter()  # type: ignore[abstract]

    def test_has_all_abstract_methods(self) -> None:
        expected = {"generate", "format_name"}
        assert expected == BaseReporter.__abstractmethods__

    def test_concrete_impl_works(self) -> None:
        class DummyReporter(BaseReporter):
            async def generate(self, result: TestResult | LoopResult, output_dir: Path) -> Path:
                return output_dir / "report.md"

            @property
            def format_name(self) -> str:
                return "markdown"

        reporter = DummyReporter()
        assert isinstance(reporter, BaseReporter)
        assert reporter.format_name == "markdown"
