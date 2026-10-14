"""The text landed somewhere. The question is whether it landed where the
scenario pointed.

A 21-step signup run scored steps 7, 9 and 10 ``PASSED`` and submitted a form
that came back "이름을 입력해주세요." -- the name box and the password box were
both empty and the confirm box held two passwords. Every one of the four value
rules AAT-123 added agreed the steps had worked, and all four were right about
the only thing they look at: the field that received the keystrokes holds text,
is not a ``<select>``, and is neither readonly nor disabled. What none of them
can see is that it is the wrong field.

The cause is in ``_find_input_field``, which tries a placeholder *substring*
match before an authored label:

    '이름'  → input[placeholder*="이름"] → #school  ('학교 이름을 입력하세요 …')
    '비밀번호' → input[placeholder*="비밀번호"] → #password-confirm  ('비밀번호 재입력')

and ``#password`` is reachable by neither, because its placeholder is '8자 이상'.
So step 9 ('비밀번호') and step 10 ('비밀번호 확인') both wrote into one box.

Two things have to hold together here, and the file is in two halves because of
it.

The resolution is fixed, which ``/longform`` proves: one route now runs ahead
of the partial matches -- the single *visible* field whose authored label is
exactly the target text. It is the verdict's own question, asked while
searching instead of only while judging, so where the page says which field was
meant the text goes there. The two routes it precedes are both left exactly
where they were, because both are substring matches and between two substring
matches there is no principled winner.

The verdict is not thereby redundant, which ``/overlaid`` proves: the search
resolves to the right field and the keystrokes still miss it, because an
autocomplete panel covers the box. Resolution is also only one of the ways a
click reaches a point -- a remembered coordinate, a hand-written ``click_at``, a
healed template and a canvas redraw are others, and none of them consult a
label. The devices are the net under all of them.

Both directions are measured. ``/cleanform`` is the same four fields with
placeholders that do not name each other, and a warning there would mean the
devices cost more than they are worth. ``/nolabel``, ``/shimform``, ``/advance``
and ``/richtext`` pin the places this stays quiet by choice.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aat.core.exceptions import CriticalStepError
from aat.core.models import (
    ActionType,
    EngineConfig,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from tests.fixtures.signup_form_server import signup_form_server

PASSWORD = "AwtGate2026!"


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with signup_form_server() as url:
        yield url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium. Skips the test if the browser is not installed."""
    eng = WebEngine(EngineConfig(headless=True, speed="fast", screenshot_mode="off"))
    try:
        await eng.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    try:
        yield eng
    finally:
        await eng.stop()


@pytest.fixture()
def executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    # The matcher finds nothing, so every step here is answered by the DOM
    # route the defect lived on. A matcher that could succeed would let a step
    # pass for a reason this file is not measuring.
    matcher = AsyncMock()
    matcher.find = AsyncMock(
        return_value=MatchResult(
            found=False, x=0, y=0, confidence=0.0, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(engine, matcher, Humanizer(), Waiter(), Comparator(), tmp_path)


def _type(step: int, text: str, value: str, *, critical: bool = False) -> StepConfig:
    """A find_and_type step that names its target by text, as the scenario did.

    Not by selector: a selector goes to priority 0 and never reaches the
    input-field search, so it cannot reproduce anything here.
    """
    return StepConfig(
        step=step,
        action=ActionType.FIND_AND_TYPE,
        target=TargetSpec(text=text),
        value=value,
        description=f"Type into {text}",
        critical=critical,
        humanize=False,
    )


class TestTheNamedFieldWins:
    """The resolution half. On the form from the report, each target now
    reaches the field whose label says it is the one."""

    async def test_an_authored_label_beats_someone_elses_placeholder(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """Step 7 of the real run, on the form that produced it. '이름' is a
        substring of the school box's placeholder ('학교 이름을 입력하세요 …') and
        that box comes first in the document, which is how the text got there.
        """
        await engine.navigate(f"{base_url}/longform")
        # Step 4 first, because the school box holding a value is what made the
        # original defect legible: the name step appended to it.
        assert (await executor.execute_step(_type(4, "학교", "인천하늘고등학교"))).status == (
            StepStatus.PASSED
        )

        result = await executor.execute_step(_type(7, "이름", "에이더블유티점검"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#name") == "에이더블유티점검"
        # And the box that used to swallow it still holds only its own value.
        assert await engine.page.input_value("#school") == "인천하늘고등학교"

    async def test_a_field_no_partial_match_can_reach_is_reachable(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The pair that collided. '비밀번호' matched the *confirm* box by
        placeholder ('비밀번호 재입력'), and ``#password`` was reachable by nothing
        at all because its placeholder is '8자 이상' -- so both steps wrote into
        one box. Each now fills its own, which is the defect inverted."""
        await engine.navigate(f"{base_url}/longform")

        ninth = await executor.execute_step(_type(9, "비밀번호", PASSWORD))
        tenth = await executor.execute_step(_type(10, "비밀번호 확인", PASSWORD))

        assert ninth.status == StepStatus.PASSED, ninth.error_message
        assert tenth.status == StepStatus.PASSED, tenth.error_message
        assert await engine.page.input_value("#password") == PASSWORD
        assert await engine.page.input_value("#password-confirm") == PASSWORD

    async def test_the_step_that_always_resolved_correctly_still_passes(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """'학교' was never ambiguous on this page and must stay green."""
        await engine.navigate(f"{base_url}/longform")
        result = await executor.execute_step(_type(4, "학교", "인천하늘고등학교"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#school") == "인천하늘고등학교"

    async def test_a_placeholder_only_form_still_resolves(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The new route answers ``None`` on a form with no authored labels, and
        the rest of the chain has to carry on unchanged. Without this the fix
        could be a silent regression on every unlabelled form on the web."""
        await engine.navigate(f"{base_url}/nolabel")
        result = await executor.execute_step(_type(2, "성함", "에이더블유티점검"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#name") == "에이더블유티점검"

    async def test_a_phrased_target_reaches_the_field_its_prefix_names(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A target written as a phrase falls through to the short-prefix
        branch, which needs the same route for the same reason.

        '이름 입력' reaches none of the full-text routes on this page: the
        placeholders read '이름을 입력', so no substring of them is '이름 입력',
        and no label contains the phrase either. Resolution then retries on the
        prefix '이름' -- and at that point the hazard is back exactly as it was,
        because '이름' is a substring of the school box's placeholder. Scenario
        text comes out of a generator and a person's typing, so it is phrased
        this way often enough to matter.
        """
        await engine.navigate(f"{base_url}/longform")
        result = await executor.execute_step(_type(7, "이름 입력", "에이더블유티점검"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#name") == "에이더블유티점검"
        assert await engine.page.input_value("#school") == ""

    async def test_two_fields_with_one_label_defer_to_the_rest_of_the_chain(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """Exactness is not enough on its own -- the label also has to be
        unique. Two fields labelled '주소' means the page has not said which one,
        and taking the first would be the route inventing an answer. It declines
        and the placeholder decides, which is the second field here."""
        await engine.navigate(f"{base_url}/twinlabel")
        result = await executor.execute_step(_type(2, "주소", "인천 서구"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#addr-new") == "인천 서구"
        assert await engine.page.input_value("#addr-old") == ""

    async def test_a_label_on_a_field_hidden_from_assistive_tech_is_declined(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The labelled field is a decorative mirror: laid out, so
        ``bounding_box()`` answers for it and the loop's existing safety net
        does not catch it, but ``aria-hidden`` and therefore not a box anyone
        types into. Only the route's own visibility predicate keeps the text
        away from it -- and it is the same predicate the verdict reads, so a
        field declined here is a field the verdict also stays quiet about."""
        await engine.navigate(f"{base_url}/ariahidden")
        result = await executor.execute_step(_type(3, "도시", "인천"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#city-search") == "인천"
        assert await engine.page.input_value("#city-mirror") == ""


class TestTextInTheWrongField:
    """Requirement (2): the verdict compares the field the step named against
    the field that took the text.

    Measured on ``/overlaid``, where the search gets it *right* -- the name box
    carries ``<label for>`` and is what resolution picks -- and an autocomplete
    panel on top of it takes the keystrokes. Fixing resolution does not retire
    this check; it only removes one of the ways the two can diverge.
    """

    async def test_the_reported_step_is_not_a_pass(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/overlaid")
        result = await executor.execute_step(_type(7, "이름", "에이더블유티점검"))

        assert result.status == StepStatus.WARNING, result.error_message
        assert result.error_message is not None
        # The message has to name both fields. "Typing may have failed" on a
        # step that looks like it worked sends the reader to the wrong place.
        assert "#suggest" in result.error_message
        assert "#name" in result.error_message
        assert "target.selector" in result.error_message
        # And the page has to agree: the named box really is empty, and this is
        # a covered field rather than a mis-resolved one.
        assert await engine.page.input_value("#name") == ""
        assert await engine.page.input_value("#suggest") == "에이더블유티점검"

    async def test_critical_makes_it_a_failure(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """Same evidence, louder, when the author said the step matters. A
        critical step stops the run rather than returning a result, so the
        evidence has to survive into the exception the runner sees."""
        await engine.navigate(f"{base_url}/overlaid")
        with pytest.raises(CriticalStepError) as caught:
            await executor.execute_step(_type(7, "이름", "에이더블유티점검", critical=True))

        assert "#name" in str(caught.value)
        assert "#suggest" in str(caught.value)


class TestTwoTargetsOneField:
    """Requirement (1): a field already filled for a different target is not a
    place a later step can be said to have succeeded.

    Measured on ``/nolabel``, which is where two targets can still land in one
    box: nothing on that page says which field '이름' meant, so the new route
    declines, a placeholder substring picks the school box for both targets,
    and rule (2) stays silent by design. What is left to report is the
    collision, and this is the shape in which device (1) is the only reporter.
    """

    async def test_both_steps_are_reported(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/nolabel")

        ninth = await executor.execute_step(_type(9, "이름", "에이더블유티점검"))
        tenth = await executor.execute_step(_type(10, "학교", "인천하늘고등학교"))

        # Step 9 is a pass: '이름' went to the wrong box, and with no authored
        # label on the page there is no evidence of where it belonged.
        assert ninth.status == StepStatus.PASSED, ninth.error_message

        # Step 10 named the school box and resolved to it correctly -- so rule
        # (2) has nothing to say. It is only not a pass because step 9 already
        # spent that field, which is exactly the hole device (1) fills.
        assert tenth.status == StepStatus.WARNING, tenth.error_message
        assert tenth.error_message is not None
        assert "step 9" in tenth.error_message
        assert "이름" in tenth.error_message

        # The page agrees: one box holds both, and #name was never filled.
        # Not asserted as a concatenation -- the second click lands mid-text so
        # the caret sits inside what step 9 typed and the value interleaves.
        # Which is the same reason no rule compares the typed string against
        # the resulting value: a box can hold what it was given without the
        # value ever equalling it.
        assert await engine.page.input_value("#name") == ""
        school = await engine.page.input_value("#school")
        assert "에이더블유티" in school and "인천하늘고등학교" in school, school

    async def test_retyping_the_same_target_is_not_a_collision(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A scenario that fills a field, navigates and fills it again names the
        same thing both times. That is a retry, not two targets sharing a box."""
        await engine.navigate(f"{base_url}/cleanform")
        first = await executor.execute_step(_type(4, "학교", "가락고등학교"))
        second = await executor.execute_step(_type(9, "학교", "하늘고등학교"))

        assert first.status == StepStatus.PASSED, first.error_message
        assert second.status == StepStatus.PASSED, second.error_message

    async def test_the_claim_is_element_identity_not_a_coordinate(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A form moves while it is being filled -- a validation message
        appears, an autocomplete list opens, a section expands -- so one
        viewport point denotes different elements at different moments. Keying
        the claim on the point would lose this collision; keying it on the
        element does not.

        Scrolling the window would *not* show this, which is the trap here: the
        search calls `scroll_into_view_if_needed` before it measures, so it
        parks the field back at nearly the same viewport y and a
        coordinate-keyed claim would still match. (That parking is also why the
        reported run logged two different targets at one point.) So the field is
        moved while staying in view, and the move is measured -- if the banner
        does not shift it, this fails rather than passing on a coordinate that
        never changed.
        """
        await engine.navigate(f"{base_url}/nolabel")
        await executor.execute_step(_type(9, "이름", "에이더블유티점검"))

        top = "document.querySelector('#school').getBoundingClientRect().top"
        before = await engine.page.evaluate(top)
        await engine.page.evaluate(
            "document.querySelector('#signup').insertAdjacentHTML('afterbegin',"
            " '<p style=\"height:180px;color:#c00\">이름을 입력해주세요.</p>')"
        )
        after = await engine.page.evaluate(top)
        assert round(after) != round(before), (
            "the field did not move, so this cannot tell the two keyings apart"
        )
        assert after < await engine.page.evaluate("window.innerHeight"), (
            "the field left the viewport, so the search will scroll and the "
            "measurement above no longer describes what it sees"
        )

        tenth = await executor.execute_step(_type(10, "학교", "인천하늘고등학교"))

        assert tenth.status == StepStatus.WARNING, tenth.error_message
        assert "step 9" in (tenth.error_message or "")


class TestWhatMustStayGreen:
    """The other direction. Devices that fire on healthy forms are worse than
    no devices, because the reader learns to skip yellow."""

    async def test_a_form_without_the_hazard_reports_nothing(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/cleanform")
        results = [
            await executor.execute_step(_type(1, "학교", "인천하늘고등학교")),
            await executor.execute_step(_type(2, "이름", "에이더블유티점검")),
            await executor.execute_step(_type(3, "비밀번호", PASSWORD)),
        ]

        assert [r.status for r in results] == [StepStatus.PASSED] * 3, [
            r.error_message for r in results
        ]

    async def test_a_reformatting_field_is_not_a_warning(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The phone box rewrites what it is given. Its value is never the
        keystrokes, and that is not a defect -- so nothing may compare them."""
        await engine.navigate(f"{base_url}/cleanform")
        result = await executor.execute_step(_type(5, "전화번호", "01012345678"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#phone") == "010-1234-5678"

    async def test_focus_moving_on_is_not_a_warning(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A form that mirrors the field into a display name and hands focus
        on. The focused element is not the field the step named, and both hold
        the text -- so two elements merely differing cannot be the claim."""
        await engine.navigate(f"{base_url}/advance")
        result = await executor.execute_step(_type(2, "이름", "에이더블유티점검"))

        assert result.status == StepStatus.PASSED, result.error_message
        # The shape the guard exists for: named field filled, focus elsewhere,
        # and the text visible in both.
        assert await engine.page.input_value("#name") == "에이더블유티점검"
        assert await engine.page.input_value("#nickname") == "에이더블유티점검"
        assert await engine.page.evaluate("document.activeElement.id") == "nickname"

    async def test_an_unlabelled_form_stays_quiet(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The text does go to the wrong box here, and AWT says nothing --
        because nothing on the page says which box '이름' meant. Guessing from a
        placeholder is what misdirected the text in the first place."""
        await engine.navigate(f"{base_url}/nolabel")
        result = await executor.execute_step(_type(7, "이름", "에이더블유티점검"))

        assert result.status == StepStatus.PASSED, result.error_message
        # Proof the test is measuring silence and not a correct resolution.
        assert await engine.page.input_value("#school") == "에이더블유티점검"
        assert await engine.page.input_value("#name") == ""

    async def test_a_hidden_named_field_stays_quiet(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A component library whose `<label for>` points at the input holding
        the committed value, not at the box you type in. The named field is
        empty and the text is elsewhere, and calling that a defect would warn
        on every autocomplete on the web."""
        await engine.navigate(f"{base_url}/shimform")
        result = await executor.execute_step(_type(3, "도시", "인천"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#city-search") == "인천"


class TestAmbiguityIsSaidOutLoud:
    """Requirement (3): which field a target text meant is not decided in
    silence."""

    async def test_the_choice_is_logged_when_an_exact_label_exists_elsewhere(
        self,
        executor: StepExecutor,
        engine: WebEngine,
        base_url: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``/shimform`` is where a choice is still made quietly now that an
        exact visible label wins outright: the field labelled '도시' is the
        hidden value holder, so the new route declines it and a placeholder
        picks the search box. Typing there is right -- that is why the verdict
        stays silent on this page -- but the author should know the page says
        '도시' means something else.
        """
        await engine.navigate(f"{base_url}/shimform")
        with caplog.at_level(logging.WARNING, logger="aat.engine.executor"):
            await executor.execute_step(_type(3, "도시", "인천"))

        ambiguity = [r for r in caplog.records if "labelled exactly" in r.getMessage()]
        assert ambiguity, [r.getMessage() for r in caplog.records]
        said = ambiguity[0].getMessage()
        # Both candidates and the way out, or the line is just noise.
        assert "#city-search" in said
        assert "#city-value" in said
        assert "target.selector" in said

    async def test_nothing_is_logged_when_there_was_no_choice(
        self,
        executor: StepExecutor,
        engine: WebEngine,
        base_url: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """'비밀번호' being a prefix of '비밀번호 확인' is true of nearly every signup
        form. Saying so every time is how a warning becomes furniture."""
        await engine.navigate(f"{base_url}/cleanform")
        with caplog.at_level(logging.WARNING, logger="aat.engine.executor"):
            await executor.execute_step(_type(3, "비밀번호", PASSWORD))

        assert not [r for r in caplog.records if "labelled exactly" in r.getMessage()]

    async def test_nothing_is_logged_when_the_chosen_field_is_the_labelled_one(
        self,
        executor: StepExecutor,
        engine: WebEngine,
        base_url: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The chosen element is a rich-text box rather than an `<input>`, and
        it carries the asked-for label itself. There is nothing to disambiguate:
        naming the plain field as the "exact" one would report a choice that was
        not wrong. This is the only reason the probe asks about the chosen
        element before it looks at the others -- for anything inside
        `input, textarea, select` the later check already covers it.
        """
        await engine.navigate(f"{base_url}/richtext")
        with caplog.at_level(logging.WARNING, logger="aat.engine.executor"):
            await executor.execute_step(_type(1, "메모", "적어 둘 것"))

        chosen = await engine.page.evaluate("document.activeElement && document.activeElement.id")
        assert chosen == "memo-editor", (
            f"the editor was not what the search chose ({chosen!r}), so this "
            "test is not exercising a non-form target at all"
        )
        assert not [r for r in caplog.records if "labelled exactly" in r.getMessage()]
