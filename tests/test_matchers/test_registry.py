"""Tests for build_matchers — the single assembly point for the matcher chain.

These exist because six call sites used to assemble the chain by hand and had
drifted apart. Four of them passed a ``MatchingConfig`` into the positional
``vision_config`` slot, so ``VisionAIMatcher.can_handle`` raised
``AttributeError`` on every call and ``HybridMatcher.find`` swallowed it —
vision matching was dead in ``aat start`` and every dashboard run, silently.
"""

from __future__ import annotations

import logging

import pytest

from aat.core.models import AIConfig, MatchingConfig, MatchMethod, TargetSpec, VisionConfig
from aat.matchers import build_matchers


def _names(matchers: list[object]) -> list[str]:
    return [m.name for m in matchers]  # type: ignore[attr-defined]


class TestBuildMatchers:
    def test_default_chain_order_builds_every_entry(self) -> None:
        """Nothing in the default chain may be dropped.

        The old default opened with ``learned``, which names no matcher, so the
        config advertised a first-priority matcher that never existed.
        """
        cfg = MatchingConfig()
        assert _names(build_matchers(cfg)) == ["template", "ocr", "feature", "vision_ai"]

    def test_vision_matcher_receives_the_vision_config(self) -> None:
        """The defect this function was written for.

        ``VisionAIMatcher(cfg)`` bound a ``MatchingConfig`` to the positional
        ``vision_config`` slot, so ``can_handle`` looked for ``.api_key`` on it
        and raised ``AttributeError`` — which ``HybridMatcher.find`` swallowed.

        Asserting ``True`` rather than merely "does not raise" also catches the
        opposite mistake of passing no config at all, which would leave Tier 3
        permanently declining every target.
        """
        matchers = build_matchers(
            MatchingConfig(),
            vision=VisionConfig(provider="claude", api_key="sk-test"),
        )
        vision = next(m for m in matchers if m.name == "vision_ai")
        assert vision.can_handle(TargetSpec(text="Login")) is True

    def test_vision_matcher_accepts_legacy_ai_config(self) -> None:
        """``ai=`` must reach the legacy ``ai_config`` keyword, not a positional."""
        matchers = build_matchers(
            MatchingConfig(),
            ai=AIConfig(provider="claude", api_key="sk-test"),
        )
        vision = next(m for m in matchers if m.name == "vision_ai")
        assert vision.can_handle(TargetSpec(text="Login")) is True

    def test_vision_declines_when_unconfigured(self) -> None:
        """Appending Tier 3 must stay free when the user has no vision key."""
        matchers = build_matchers(MatchingConfig())
        vision = next(m for m in matchers if m.name == "vision_ai")
        assert vision.can_handle(TargetSpec(text="Login")) is False

    def test_unknown_entry_is_reported_not_silently_dropped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg = MatchingConfig(chain_order=[MatchMethod.LEARNED, MatchMethod.TEMPLATE])
        with caplog.at_level(logging.WARNING, logger="aat.matchers"):
            matchers = build_matchers(cfg, include_vision=False)

        assert _names(matchers) == ["template"]
        assert "learned" in caplog.text
        # The warning must say where the work happens, not just that something
        # was skipped — otherwise the user removes the entry and loses nothing,
        # or keeps it and still believes it does something.
        assert "step executor" in caplog.text

    def test_playwright_entry_is_reported(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``playwright`` became a MatchMethod so match_history could tell a
        selector hit from a visual one. That made it newly writable in
        ``chain_order``, where it means nothing — DOM lookup always runs first,
        inside the executor. Saying so beats dropping it in silence.
        """
        cfg = MatchingConfig(chain_order=[MatchMethod.PLAYWRIGHT, MatchMethod.TEMPLATE])
        with caplog.at_level(logging.WARNING, logger="aat.matchers"):
            matchers = build_matchers(cfg, include_vision=False)

        assert _names(matchers) == ["template"]
        assert "playwright" in caplog.text
        assert "step executor" in caplog.text

    def test_semantics_entry_is_reported(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg = MatchingConfig(chain_order=[MatchMethod.SEMANTICS, MatchMethod.OCR])
        with caplog.at_level(logging.WARNING, logger="aat.matchers"):
            matchers = build_matchers(cfg, include_vision=False)

        assert _names(matchers) == ["ocr"]
        assert "semantics" in caplog.text

    def test_include_vision_false_omits_vision(self) -> None:
        """Visual-regression commands must not reach for a paid API."""
        matchers = build_matchers(MatchingConfig(), include_vision=False)
        assert "vision_ai" not in _names(matchers)

    def test_vision_appended_when_chain_omits_it(self) -> None:
        """Tier 3 stays reachable even if the chain does not name it.

        It declines every target when no API key is set, so appending it costs
        nothing when vision is unconfigured.
        """
        cfg = MatchingConfig(chain_order=[MatchMethod.TEMPLATE])
        assert _names(build_matchers(cfg)) == ["template", "vision_ai"]

    def test_vision_not_duplicated(self) -> None:
        cfg = MatchingConfig(chain_order=[MatchMethod.VISION_AI, MatchMethod.TEMPLATE])
        assert _names(build_matchers(cfg)).count("vision_ai") == 1

    def test_hybrid_entry_is_refused(self) -> None:
        """HybridMatcher orchestrates the chain; it cannot be a member of it."""
        cfg = MatchingConfig()
        matchers = build_matchers(cfg, include_vision=False)
        assert "hybrid" not in _names(matchers)

    def test_chain_order_is_honoured(self) -> None:
        cfg = MatchingConfig(chain_order=[MatchMethod.OCR, MatchMethod.TEMPLATE])
        assert _names(build_matchers(cfg, include_vision=False)) == ["ocr", "template"]

    def test_matchers_receive_the_matching_config(self) -> None:
        cfg = MatchingConfig(confidence_threshold=0.42)
        matchers = build_matchers(cfg, include_vision=False)
        template = next(m for m in matchers if m.name == "template")
        assert template._config.confidence_threshold == 0.42  # type: ignore[attr-defined]
