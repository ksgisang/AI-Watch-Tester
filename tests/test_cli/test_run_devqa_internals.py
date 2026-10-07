"""The parts of `aat run` and `aat devqa` that run before a browser exists.

These two commands are the product's face and had the thinnest cover in it:
15% of `run_cmd.py` and 9% of `devqa_cmd.py` ran under test, so a regression
in either could land with the whole suite green. The report named that gap as
the third-priority item and the reason was never that the commands are hard to
test -- it is that the testable parts are small functions nobody went looking
for, buried under an async body that does need a browser.

Writing these found two defects, both in code that had never been called by a
test: `_js_str` left line terminators intact, and the devqa auto-fixer crashed
on the only path where it had anything to fix.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
import yaml

from aat.cli.commands.devqa_cmd import (
    _devqa,
    _find_matching_elements,
    _fix_scenario,
    _print_devqa_verdict,
    _read_last_failure,
)
from aat.cli.commands.run_cmd import _js_str, _scenario_to_yaml, _topo_sort
from aat.core.exceptions import AATError
from aat.core.models import ActionType, Scenario, StepConfig, TargetSpec


def _scenario(sid: str, *, depends_on: list[str] | None = None) -> Scenario:
    return Scenario(
        id=sid,
        name=sid,
        depends_on=depends_on or [],
        steps=[StepConfig(step=1, action=ActionType.REFRESH, description="refresh")],
    )


class TestJsStringLiteral:
    """Text from a scenario becomes part of a JS program, so it must survive.

    The browser overlay interpolates step descriptions into `page.evaluate`.
    The old escaper handled the backslash and the quote, which is enough for
    the cases a person thinks of, and left every line terminator alone -- so a
    description wrapped onto a second line produced a JS syntax error. The
    caller swallows errors to keep a cosmetic overlay from failing a test run,
    which means the only symptom was a progress banner that stopped counting
    and no message anywhere.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "plain",
            "it's quoted",
            r"back\slash",
            'double "quoted"',
            "line\nbreak",
            "carriage\rreturn",
            "para separator",
            "line separator",
            "한글 설명",
            "",
        ],
    )
    def test_it_round_trips_through_json(self, raw: str) -> None:
        """The literal must parse back to exactly the text that went in.

        JSON string syntax is a subset of JS string syntax, so parsing the
        literal as JSON asks the same question a browser would.
        """
        assert json.loads(_js_str(raw)) == raw

    @pytest.mark.parametrize("terminator", ["\n", "\r", " ", " "])
    def test_no_line_terminator_survives_raw(self, terminator: str) -> None:
        """The regression. Each of these ends a string literal in JS.

        U+2028 and U+2029 are the pair that catches people out: JS treats them
        as line terminators and JSON does not, so an escaper that only thought
        about `\\n` would still break on text pasted from a word processor.
        """
        assert terminator not in _js_str(f"before{terminator}after")

    def test_a_quote_cannot_close_the_literal_early(self) -> None:
        literal = _js_str("'); alert(1); ('")

        assert json.loads(literal) == "'); alert(1); ('"


class TestTopoSort:
    """`depends_on` decides execution order, and nothing else checks it.

    A scenario that logs in before another one reads a dashboard is the common
    case, and getting the order wrong does not look like an ordering bug — it
    looks like the second scenario failing to find a logged-in page.
    """

    def test_a_dependency_runs_first(self) -> None:
        dash = _scenario("SC-002", depends_on=["SC-001"])
        login = _scenario("SC-001")

        order = [s.id for s in _topo_sort([dash, login])]

        assert order == ["SC-001", "SC-002"]

    def test_independent_scenarios_keep_their_given_order(self) -> None:
        """Otherwise the file order a person wrote stops meaning anything."""
        scenarios = [_scenario("SC-003"), _scenario("SC-001"), _scenario("SC-002")]

        assert [s.id for s in _topo_sort(scenarios)] == ["SC-003", "SC-001", "SC-002"]

    def test_a_shared_dependency_runs_once(self) -> None:
        order = [
            s.id
            for s in _topo_sort(
                [
                    _scenario("SC-002", depends_on=["SC-001"]),
                    _scenario("SC-003", depends_on=["SC-001"]),
                    _scenario("SC-001"),
                ]
            )
        ]

        assert order.count("SC-001") == 1
        assert order.index("SC-001") == 0

    def test_a_cycle_is_refused_rather_than_resolved(self) -> None:
        """Picking an order here would be inventing one."""
        with pytest.raises(AATError, match="Circular dependency"):
            _topo_sort(
                [
                    _scenario("SC-001", depends_on=["SC-002"]),
                    _scenario("SC-002", depends_on=["SC-001"]),
                ]
            )

    def test_a_scenario_depending_on_itself_is_a_cycle(self) -> None:
        with pytest.raises(AATError, match="Circular dependency"):
            _topo_sort([_scenario("SC-001", depends_on=["SC-001"])])

    def test_a_dependency_outside_the_selection_is_skipped(self) -> None:
        """Running one scenario out of a suite must not fail on the others.

        `aat run` is routinely pointed at a single file, and `--scenario-ids`
        narrows a directory. Either way the named dependency may simply not be
        in the set, and that is not an error.
        """
        order = [s.id for s in _topo_sort([_scenario("SC-002", depends_on=["SC-404"])])]

        assert order == ["SC-002"]


class TestScenarioToYaml:
    """The approval panel shows this text, so it has to say what will run.

    A field dropped here is a field the person approving never sees, which is
    the same failure the empty-assertion panel was (§7-6-2): the gate is only
    worth having if what it displays is what executes.
    """

    def test_a_target_survives_the_round_trip(self) -> None:
        scenario = Scenario(
            id="SC-001",
            name="login",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.FIND_AND_CLICK,
                    description="Click login",
                    target=TargetSpec(text="Log in", selector="#login"),
                )
            ],
        )

        parsed = yaml.safe_load(_scenario_to_yaml(scenario))

        assert parsed["steps"][0]["target"] == {"text": "Log in", "selector": "#login"}
        assert parsed["steps"][0]["description"] == "Click login"

    def test_critical_is_shown_because_it_changes_what_failure_means(self) -> None:
        """A critical step stops the run and skips the rest of it."""
        scenario = Scenario(
            id="SC-001",
            name="login",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.NAVIGATE,
                    value="/",
                    description="open",
                    critical=True,
                )
            ],
        )

        assert yaml.safe_load(_scenario_to_yaml(scenario))["steps"][0]["critical"] is True

    def test_korean_text_is_readable_not_escaped(self) -> None:
        """`allow_unicode=False` would print `\\uXXXX` to a Korean reviewer."""
        scenario = Scenario(
            id="SC-001",
            name="로그인",
            steps=[StepConfig(step=1, action=ActionType.REFRESH, description="새로고침")],
        )

        assert "새로고침" in _scenario_to_yaml(scenario)


class TestDevqaRematch:
    """What `aat devqa` means by "fixing" the scenario.

    Not AI, and not source code: about forty lines that swap `target.text` and
    `target.selector` for a fresher label from a rescan. The tests below pin
    both what it does and the much larger set of renames it cannot do, because
    the name promises more than the code delivers and the retry it drives looks
    identical either way.
    """

    SCAN = {"elements": [{"label": "Log in now", "source": "dom", "selector": "#login"}]}

    def _yaml(self, *, description: str | None = None) -> str:
        step: dict[str, object] = {
            "step": 1,
            "action": "find_and_click",
            "target": {"text": "Log in"},
        }
        if description is not None:
            step["description"] = description
        return yaml.safe_dump({"id": "SC-001", "name": "t", "steps": [step]})

    def test_a_grown_label_is_picked_up(self) -> None:
        fixed = yaml.safe_load(
            _fix_scenario(self._yaml(description="click"), self.SCAN, {"step": 1}, 1)
        )

        assert fixed["steps"][0]["target"]["text"] == "Log in now"
        assert fixed["steps"][0]["target"]["selector"] == "#login"

    def test_a_step_with_no_description_no_longer_crashes(self) -> None:
        """Latent rather than live, and pinned as the former.

        The annotation was written with `+=`, which assumes the key is there.
        `description` is required by `StepConfig` and every step the devqa
        generator builds sets it, so devqa's own loop could not reach this —
        but the function takes raw YAML, so a hand-edited file would have
        raised KeyError on the one branch where the fixer had found a
        replacement, after the user had already approved the run.
        """
        fixed = yaml.safe_load(_fix_scenario(self._yaml(), self.SCAN, {"step": 1}, 1))

        assert fixed["steps"][0]["target"]["text"] == "Log in now"
        assert "auto-fixed attempt 1" in fixed["steps"][0]["description"]

    def test_the_annotation_is_not_repeated_across_attempts(self) -> None:
        once = _fix_scenario(self._yaml(description="click"), self.SCAN, {"step": 1}, 1)
        twice = _fix_scenario(once, self.SCAN, {"step": 1}, 1)

        assert yaml.safe_load(twice)["steps"][0]["description"].count("auto-fixed attempt 1") == 1

    def test_a_renamed_label_is_not_found(self) -> None:
        """Pinned as the limit it is, not asserted as correct behaviour.

        "Login" -> "Sign in" shares no substring, and a rename is the usual
        reason a step stops working, so the fixer is quiet in the case it most
        needs to handle. The scenario comes back unchanged and the retry fails
        the same way, which reads as "tried and failed" rather than "found
        nothing to try". Fixing it means fuzzy or positional matching, and that
        is a behaviour change: a wrong rematch silently points the scenario at
        a different button. If it is fixed, this test should flip.
        """
        renamed = {"elements": [{"label": "Sign in", "source": "dom", "selector": "#signin"}]}

        unchanged = yaml.safe_load(
            _fix_scenario(self._yaml(description="c"), renamed, {"step": 1}, 1)
        )

        assert unchanged["steps"][0]["target"]["text"] == "Log in"

    def test_only_the_failed_step_is_touched(self) -> None:
        two_steps = yaml.safe_dump(
            {
                "id": "SC-001",
                "name": "t",
                "steps": [
                    {"step": 1, "action": "find_and_click", "target": {"text": "Log in"}},
                    {"step": 2, "action": "find_and_click", "target": {"text": "Log in"}},
                ],
            }
        )

        fixed = yaml.safe_load(_fix_scenario(two_steps, self.SCAN, {"step": 2}, 1))

        assert fixed["steps"][0]["target"]["text"] == "Log in"
        assert fixed["steps"][1]["target"]["text"] == "Log in now"

    def test_unparseable_yaml_comes_back_untouched(self) -> None:
        """Better the original than a file the loader can no longer read."""
        broken = "steps: [unclosed"

        assert _fix_scenario(broken, self.SCAN, {"step": 1}, 1) == broken

    def test_an_ocr_label_does_not_become_a_selector(self) -> None:
        """An OCR reading is a guess at text; it is not a CSS selector.

        Writing one into `target.selector` would produce a selector that can
        never match, turning a findable step into a permanent failure.
        """
        ocr_scan = {"elements": [{"label": "Log in now", "source": "ocr", "selector": "#guess"}]}

        fixed = yaml.safe_load(
            _fix_scenario(self._yaml(description="c"), ocr_scan, {"step": 1}, 1)
        )

        assert "selector" not in fixed["steps"][0]["target"]


class TestElementMatchPriority:
    """Which rescanned element wins when several labels match."""

    def test_dom_beats_ocr(self) -> None:
        """DOM gives a selector; OCR gives a reading of some pixels."""
        matches = _find_matching_elements(
            "save",
            [
                {"label": "Save", "source": "ocr"},
                {"label": "Save", "source": "dom"},
            ],
        )

        assert matches[0]["source"] == "dom"

    def test_semantics_beats_dom(self) -> None:
        """Flutter semantics is the only reliable route into a canvas app."""
        matches = _find_matching_elements(
            "save",
            [
                {"label": "Save", "source": "dom"},
                {"label": "Save", "source": "semantics"},
            ],
        )

        assert matches[0]["source"] == "semantics"

    def test_an_unknown_source_sorts_last_rather_than_crashing(self) -> None:
        matches = _find_matching_elements(
            "save",
            [
                {"label": "Save", "source": "something-new"},
                {"label": "Save", "source": "ocr"},
            ],
        )

        assert matches[0]["source"] == "ocr"

    def test_the_match_ignores_case(self) -> None:
        assert _find_matching_elements("SAVE", [{"label": "Save changes", "source": "dom"}])

    def test_an_element_with_no_label_is_not_a_match(self) -> None:
        assert _find_matching_elements("save", [{"source": "dom"}]) == []


class TestReadLastFailure:
    """Which failure the retry is aimed at."""

    def test_the_first_failed_step_is_the_one_reported(self, tmp_path: Path) -> None:
        """Later failures are usually consequences of the first one."""
        (tmp_path / "last_run.json").write_text(
            json.dumps(
                {
                    "results": [
                        {"step": 1, "status": "passed"},
                        {"step": 2, "status": "failed", "error": "no button", "action": "click"},
                        {"step": 3, "status": "failed", "error": "later", "action": "click"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert _read_last_failure(tmp_path) == {
            "step": 2,
            "error": "no button",
            "action": "click",
        }

    def test_a_missing_file_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert _read_last_failure(tmp_path) == {}

    def test_a_run_with_no_failures_reports_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "last_run.json").write_text(
            json.dumps({"results": [{"step": 1, "status": "passed"}]}), encoding="utf-8"
        )

        assert _read_last_failure(tmp_path) == {}

    def test_corrupt_json_is_empty_not_an_error(self, tmp_path: Path) -> None:
        """A truncated file is what a cancelled run leaves behind."""
        (tmp_path / "last_run.json").write_text("{not json", encoding="utf-8")

        assert _read_last_failure(tmp_path) == {}


class TestDevqaVerdict:
    """The closing summary `aat devqa` prints (AAT-122).

    `devqa` never edits source. Everything it rewrites is the scenario's own
    locators, so the plain register has to say that in those words -- a reader
    told "AWT fixed it" would reasonably believe their site had been changed.
    """

    def _capture(
        self,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        *,
        passed: bool,
        attempts: int = 1,
        scenario_edits: int = 0,
    ) -> str:
        _print_devqa_verdict(
            passed=passed,
            attempts=attempts,
            scenario_edits=scenario_edits,
            data_dir=tmp_path,
        )
        return capsys.readouterr().out

    def test_a_clean_pass_claims_no_repair(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        out = self._capture(capsys, tmp_path, passed=True)

        assert "The test passed. Nothing needed to change." in out
        assert "Rewrote" not in out

    def test_a_rewrite_is_described_as_a_test_change_not_a_site_fix(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        out = self._capture(capsys, tmp_path, passed=True, attempts=2, scenario_edits=1)

        assert "Rewrote the test itself once" in out
        assert "not the page being wrong" in out

    def test_the_rewrite_count_is_disclosed_not_rounded_to_one(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Three rewrites to reach green is worth knowing about."""
        out = self._capture(capsys, tmp_path, passed=True, attempts=4, scenario_edits=3)

        assert "Rewrote the test itself 3 times" in out

    def test_a_failure_hands_the_problem_back_with_the_failing_step(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        (tmp_path / "last_run.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "step": 4,
                            "status": "failed",
                            "action": "find_and_click",
                            "error": "Login button not found",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        out = self._capture(capsys, tmp_path, passed=False, attempts=3, scenario_edits=2)

        assert "a person needs to look at this" in out
        assert "Step 4 (find_and_click) — Login button not found" in out
        assert "last_run.json" in out

    def test_both_registers_are_printed(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        out = self._capture(capsys, tmp_path, passed=True, attempts=2, scenario_edits=1)

        assert "Details for a developer:" in out
        assert "mode=scenario" in out
        assert "Scenario file rewrites: 1" in out

    def test_it_never_offers_a_git_undo(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """`devqa` writes no source files, so there is nothing to revert.

        `git checkout -- <path>` printed here would discard the user's own
        uncommitted work in exchange for undoing nothing.
        """
        out = self._capture(capsys, tmp_path, passed=True, attempts=3, scenario_edits=2)

        assert "git checkout" not in out
        assert "git branch -D" not in out

    def test_the_runner_prints_it_on_both_outcomes(self) -> None:
        """Asserted against the source for the same reason as the evaluator
        wiring test in `tests/integration/test_text_assertions.py`: reaching
        the end of `_devqa` needs a live browser and a `/dev/tty` approval,
        and the approval gate is not something a test may walk around.

        What a source check can prove is placement -- that the verdict is not
        parked inside the success branch, which would leave the one reader who
        most needs the plain summary (the run failed) without it.
        """
        source = inspect.getsource(_devqa)
        verdict_at = source.index("_print_devqa_verdict(")
        failure_at = source.index("_report_failure(data_dir)")
        guard_at = source.index("if not passed:")

        assert verdict_at < guard_at < failure_at

    def test_every_scenario_rewrite_is_counted(self) -> None:
        """The count is what turns "it passed" into "it passed after the test
        was rewritten three times", so a rewrite that skips the counter is a
        silent one."""
        source = inspect.getsource(_devqa)
        # Only writes inside the retry loop are rewrites; the one above it
        # creates the generated scenario in the first place.
        retry_loop = source[source.index("for attempt in range(") :]
        rewrites = retry_loop.count("scenario_path.write_text(scenario_yaml")
        counted = retry_loop.count("scenario_edits += 1")

        assert rewrites == counted == 1
