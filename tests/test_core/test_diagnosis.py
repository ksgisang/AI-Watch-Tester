"""Failure classification — what the tool tells a person to go and look at.

The distinction these tests protect came out of a live run: a reused session
had been ended by the server for inactivity, AWT called it
"wrong credentials or expired session", and the account details were searched
through for a long time over a problem that was never there.
"""

from __future__ import annotations

import pytest

from aat.core.diagnosis import (
    _INVESTIGATION_CHECKLISTS,
    classify_failure,
    describe_target,
    format_diagnosis,
    format_skill_diagnosis,
)
from aat.core.models import ActionType, AssertType, StepConfig


class TestSessionExpiryIsNotAnAuthError:
    """A dead session and a rejected password send people to different places."""

    @pytest.mark.parametrize(
        "message",
        [
            "saved session 'haneul' is too old: saved 40 minutes ago, max_age_min=15",
            "the session expired",
            "session is no longer accepted by the server",
        ],
    )
    def test_session_messages_classify_as_session_expired(self, message: str) -> None:
        assert classify_failure(message) == "session_expired"

    @pytest.mark.parametrize(
        "message",
        [
            "401 Unauthorized",
            "auth rejected: password incorrect",
            "403 Forbidden",
        ],
    )
    def test_credential_messages_still_classify_as_auth_error(self, message: str) -> None:
        assert classify_failure(message) == "auth_error"

    def test_the_two_checklists_do_not_say_the_same_thing(self) -> None:
        session = " ".join(_INVESTIGATION_CHECKLISTS["session_expired"]).lower()
        auth = " ".join(_INVESTIGATION_CHECKLISTS["auth_error"]).lower()

        assert "credentials are not in question" in session
        assert "saved session" in session
        assert session != auth


class TestThePageTitleAndTheSoughtTextAreToldApart:
    """A diagnosis that reads as a contradiction sends nobody anywhere.

    The block carried the page's ``<title>`` and no record at all of the
    string the step was hunting for -- that one lived inside the error
    sentence and nowhere else. On an app whose tab title is also its heading
    the same words therefore printed as ``PAGE_TITLE`` one line above
    "not found on page", and the reader took AWT to be contradicting itself.

    The coincidence is ordinary and is not the defect; printing the two
    without saying which is which was.
    """

    @staticmethod
    def _assert_step(value: str) -> StepConfig:
        return StepConfig(
            step=7,
            action=ActionType.ASSERT,
            assert_type=AssertType.TEXT_VISIBLE,
            expected=[{"type": "text_visible", "value": value}],
            description="the heading is on screen",
        )

    @staticmethod
    def _context(**over: object) -> dict[str, object]:
        base: dict[str, object] = {
            "step": 7,
            "action": "assert",
            "description": "the heading is on screen",
            "error": "Text '학원 관리 시스템' not visible on page",
            "failure_type": "assertion_failed",
            "page_title": "학원 관리 시스템",
            "looked_for": "text_visible '학원 관리 시스템'",
        }
        base.update(over)
        return base

    def test_an_assertion_says_what_it_was_looking_for(self) -> None:
        assert describe_target(self._assert_step("학원 관리 시스템")) == (
            "text_visible '학원 관리 시스템'"
        )

    def test_a_find_step_says_selector_and_text(self) -> None:
        step = StepConfig(
            step=3,
            action=ActionType.FIND_AND_CLICK,
            target={"selector": "#login", "text": "로그인"},
            description="press login",
        )

        described = describe_target(step)

        assert "selector '#login'" in described
        assert "text '로그인'" in described

    def test_a_caller_without_the_step_still_gets_a_block(self) -> None:
        # The parameter is optional on purpose: a caller that has no step
        # should lose this one line, not the whole diagnosis.
        assert describe_target(None) == ""

        rendered = format_skill_diagnosis(self._context(looked_for=""), "s.yaml")

        assert "LOOKED_FOR:" not in rendered
        assert "PAGE_TITLE:" in rendered

    def test_the_skill_block_names_both_strings(self) -> None:
        rendered = format_skill_diagnosis(self._context(), "s.yaml")

        assert "LOOKED_FOR: text_visible '학원 관리 시스템'" in rendered
        assert "PAGE_TITLE: 학원 관리 시스템" in rendered

    def test_a_title_that_is_the_sought_text_is_called_out(self) -> None:
        rendered = format_skill_diagnosis(self._context(), "s.yaml")

        assert "PAGE_TITLE_NOTE:" in rendered
        assert "<title> is tab metadata" in rendered

    def test_the_human_block_calls_it_out_too(self) -> None:
        rendered = format_diagnosis(self._context(), "s.yaml")

        assert "Looked for: text_visible '학원 관리 시스템'" in rendered
        assert "Page title: 학원 관리 시스템" in rendered
        assert "<title> is tab metadata" in rendered

    def test_an_ordinary_title_raises_no_note(self) -> None:
        # Nothing is confusing when the two differ, and a note on every
        # failure is a note nobody reads.
        context = self._context(page_title="ClasRing")

        assert "PAGE_TITLE_NOTE:" not in format_skill_diagnosis(context, "s.yaml")
        assert "tab metadata" not in format_diagnosis(context, "s.yaml")

    def test_a_title_merely_contained_in_a_longer_phrase_raises_no_note(self) -> None:
        # Matched on the quoted token, not by substring: a two-letter title
        # occurring inside the sought phrase is a coincidence of spelling,
        # not the same string, and claiming otherwise would teach readers to
        # ignore the note.
        context = self._context(
            page_title="관리",
            looked_for="text_visible '학원 관리 시스템'",
        )

        assert "PAGE_TITLE_NOTE:" not in format_skill_diagnosis(context, "s.yaml")

    def test_a_missing_title_raises_no_note(self) -> None:
        context = self._context(page_title="")

        assert "PAGE_TITLE_NOTE:" not in format_skill_diagnosis(context, "s.yaml")
        assert "tab metadata" not in format_diagnosis(context, "s.yaml")


class TestTheRunnerHandsOverTheStep:
    """``StepResult`` does not carry a target, so only the caller can.

    An end-to-end CLI test cannot reach this: the run path needs a browser
    and passes through the ``/dev/tty`` approval gate, and bypassing that
    gate is forbidden. The defect being guarded against here is an
    *omission* at the call site, so the call site is what gets read.
    """

    @staticmethod
    def _run_cmd_source() -> str:
        from pathlib import Path

        import aat.cli.commands.run_cmd as mod

        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_both_diagnosis_call_sites_pass_the_step(self) -> None:
        source = self._run_cmd_source()
        calls = source.count("collect_failure_context(")
        handovers = source.count("step=step")

        assert calls == 2
        assert handovers >= calls
