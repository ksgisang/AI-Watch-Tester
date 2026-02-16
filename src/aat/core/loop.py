"""DevQA Loop orchestrator."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING

from aat.core.exceptions import LoopError
from aat.core.models import (
    ApprovalMode,
    LoopIteration,
    LoopResult,
    StepStatus,
    TestResult,
)

if TYPE_CHECKING:
    from aat.adapters.base import AIAdapter
    from aat.core.git_ops import GitOps
    from aat.core.models import AnalysisResult, Config, Scenario, StepResult
    from aat.engine.base import BaseEngine
    from aat.engine.executor import StepExecutor
    from aat.reporters.base import BaseReporter


def _default_prompt_approval(analysis_text: str) -> bool:
    """Default approval callback using input()."""
    response = input(f"\nAnalysis: {analysis_text}\nApprove fix? [y/N]: ")
    return response.strip().lower() in ("y", "yes")


class DevQALoop:
    """Core DevQA Loop orchestrator.

    Runs test scenarios, analyzes failures with AI, proposes fixes,
    and re-runs until all tests pass or max_loops is reached.

    Approval modes:
        - manual: Terminal prompt, no file changes (default)
        - branch: Git branch isolation, apply + commit + retest
        - auto: Direct file changes, apply + retest
    """

    def __init__(
        self,
        config: Config,
        executor: StepExecutor,
        adapter: AIAdapter,
        reporter: BaseReporter,
        engine: BaseEngine,
        approval_callback: Callable[[str], bool] | None = None,
        git_ops: GitOps | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._adapter = adapter
        self._reporter = reporter
        self._engine = engine
        self._approval_callback = approval_callback or _default_prompt_approval
        self._git_ops = git_ops
        self._fix_counter = 0

    async def run(
        self,
        scenarios: list[Scenario],
        *,
        skip_engine_lifecycle: bool = False,
    ) -> LoopResult:
        """Run the DevQA loop.

        Args:
            scenarios: Test scenarios to execute.
            skip_engine_lifecycle: If True, do not call engine.start()/stop().
                Used when the engine is already running (e.g. from start_cmd).

        Returns:
            LoopResult with iteration history.
        """
        mode = self._config.approval_mode

        if mode == ApprovalMode.BRANCH:
            await self._validate_git_ready()

        loop_start = time.monotonic()
        iterations: list[LoopIteration] = []
        max_loops = self._config.max_loops

        try:
            if not skip_engine_lifecycle:
                await self._engine.start()

            for iteration_num in range(1, max_loops + 1):
                # Execute all scenarios
                test_result = await self._execute_scenarios(scenarios)

                if test_result.passed:
                    # All passed — record and finish
                    iterations.append(
                        LoopIteration(
                            iteration=iteration_num,
                            test_result=test_result,
                        )
                    )
                    await self._generate_report(test_result)
                    elapsed = (time.monotonic() - loop_start) * 1000
                    return LoopResult(
                        success=True,
                        total_iterations=iteration_num,
                        iterations=iterations,
                        duration_ms=elapsed,
                    )

                # Failed — analyze
                analysis = await self._adapter.analyze_failure(test_result)

                # Dispatch to mode handler
                if mode == ApprovalMode.MANUAL:
                    iteration = await self._handle_manual(
                        iteration_num,
                        test_result,
                        analysis,
                        scenarios,
                    )
                elif mode == ApprovalMode.BRANCH:
                    iteration = await self._handle_branch(
                        iteration_num,
                        test_result,
                        analysis,
                        scenarios,
                    )
                else:  # AUTO
                    iteration = await self._handle_auto(
                        iteration_num,
                        test_result,
                        analysis,
                        scenarios,
                    )

                iterations.append(iteration)

                # If user denied fix in manual mode, stop
                if iteration.approved is False:
                    elapsed = (time.monotonic() - loop_start) * 1000
                    return LoopResult(
                        success=False,
                        total_iterations=iteration_num,
                        iterations=iterations,
                        reason="user denied fix",
                        duration_ms=elapsed,
                    )

                # branch/auto modes include retest — check if already passed
                if mode != ApprovalMode.MANUAL and iteration.test_result.passed:
                    await self._generate_report(iteration.test_result)
                    elapsed = (time.monotonic() - loop_start) * 1000
                    return LoopResult(
                        success=True,
                        total_iterations=iteration_num,
                        iterations=iterations,
                        duration_ms=elapsed,
                    )

                await self._generate_report(iteration.test_result)

            # Max loops exceeded
            elapsed = (time.monotonic() - loop_start) * 1000
            return LoopResult(
                success=False,
                total_iterations=max_loops,
                iterations=iterations,
                reason="max loops exceeded",
                duration_ms=elapsed,
            )

        except LoopError:
            raise
        except Exception as exc:
            msg = f"DevQA Loop failed: {exc}"
            raise LoopError(msg) from exc
        finally:
            if not skip_engine_lifecycle:
                await self._engine.stop()

    # ------------------------------------------------------------------
    # Mode handlers
    # ------------------------------------------------------------------

    async def _handle_manual(
        self,
        iteration_num: int,
        test_result: TestResult,
        analysis: AnalysisResult,
        scenarios: list[Scenario],
    ) -> LoopIteration:
        """Manual mode: prompt approval, generate fix text only (no file changes)."""
        approved = self._approval_callback(f"{analysis.cause} — {analysis.suggestion}")

        if not approved:
            return LoopIteration(
                iteration=iteration_num,
                test_result=test_result,
                analysis=analysis,
                approved=False,
            )

        source_files = await self._read_source_files(analysis)
        fix = await self._adapter.generate_fix(analysis, source_files)

        return LoopIteration(
            iteration=iteration_num,
            test_result=test_result,
            analysis=analysis,
            fix=fix,
            approved=True,
        )

    async def _handle_branch(
        self,
        iteration_num: int,
        test_result: TestResult,
        analysis: AnalysisResult,
        scenarios: list[Scenario],
    ) -> LoopIteration:
        """Branch mode: create git branch, apply fix, commit, retest."""
        assert self._git_ops is not None  # validated in _validate_git_ready

        source_files = await self._read_source_files(analysis)
        fix = await self._adapter.generate_fix(analysis, source_files)

        self._fix_counter += 1
        branch_name = f"aat/fix-{self._fix_counter:03d}"

        async with self._git_ops.on_fix_branch(branch_name):
            written = await self._git_ops.apply_file_changes(fix.files_changed)
            commit_hash = await self._git_ops.commit_changes(
                written,
                f"aat: {fix.description}",
            )

            # Re-test on the fix branch
            retest_result = await self._execute_scenarios(scenarios)

        return LoopIteration(
            iteration=iteration_num,
            test_result=retest_result,
            analysis=analysis,
            fix=fix,
            approved=True,
            branch_name=branch_name,
            commit_hash=commit_hash,
        )

    async def _handle_auto(
        self,
        iteration_num: int,
        test_result: TestResult,
        analysis: AnalysisResult,
        scenarios: list[Scenario],
    ) -> LoopIteration:
        """Auto mode: apply fix directly, retest."""
        source_files = await self._read_source_files(analysis)
        fix = await self._adapter.generate_fix(analysis, source_files)

        # Apply changes directly to working directory
        project_root = Path(self._config.source_path)
        for change in fix.files_changed:
            file_path = project_root / change.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(change.modified, encoding="utf-8")

        # Re-test
        retest_result = await self._execute_scenarios(scenarios)

        return LoopIteration(
            iteration=iteration_num,
            test_result=retest_result,
            analysis=analysis,
            fix=fix,
            approved=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _validate_git_ready(self) -> None:
        """Validate git prerequisites for branch mode."""
        if self._git_ops is None:
            msg = "Branch mode requires GitOps instance"
            raise LoopError(msg)
        if not await self._git_ops.is_git_repo():
            msg = "Branch mode requires a git repository"
            raise LoopError(msg)
        if await self._git_ops.has_uncommitted_changes():
            msg = (
                "Branch mode requires a clean working tree. "
                "Please commit or stash your changes first."
            )
            raise LoopError(msg)

    async def _read_source_files(
        self,
        analysis: AnalysisResult,
    ) -> dict[str, str]:
        """Read source files referenced in the analysis."""
        source_files: dict[str, str] = {}
        project_root = Path(self._config.source_path)
        for rel_path in analysis.related_files:
            file_path = project_root / rel_path
            if file_path.is_file():
                with contextlib.suppress(OSError):
                    source_files[rel_path] = file_path.read_text(encoding="utf-8")
        return source_files

    async def _execute_scenarios(
        self,
        scenarios: list[Scenario],
    ) -> TestResult:
        """Execute all scenarios and build a TestResult.

        For the ultra-MVP, scenarios are combined into one TestResult.
        """
        all_steps: list[StepResult] = []
        total_elapsed = 0.0

        for scenario in scenarios:
            for step_config in scenario.steps:
                step_result = await self._executor.execute_step(step_config)
                all_steps.append(step_result)
                total_elapsed += step_result.elapsed_ms

        passed_count = sum(1 for s in all_steps if s.status == StepStatus.PASSED)
        failed_count = sum(
            1 for s in all_steps if s.status in (StepStatus.FAILED, StepStatus.ERROR)
        )

        # Use the first scenario for naming
        scenario_id = scenarios[0].id if scenarios else "SC-000"
        scenario_name = scenarios[0].name if scenarios else "Unknown"

        return TestResult(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            passed=failed_count == 0,
            steps=all_steps,
            total_steps=len(all_steps),
            passed_steps=passed_count,
            failed_steps=failed_count,
            duration_ms=total_elapsed,
        )

    async def _generate_report(self, test_result: TestResult) -> None:
        """Generate a report for the given test result."""
        output_dir = Path(self._config.reports_dir)
        await self._reporter.generate(test_result, output_dir)
