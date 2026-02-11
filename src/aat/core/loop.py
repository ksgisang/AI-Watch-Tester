"""DevQA Loop orchestrator."""

from __future__ import annotations

import time
from collections.abc import Callable  # noqa: TC003
from typing import TYPE_CHECKING

from aat.core.exceptions import LoopError
from aat.core.models import (
    LoopIteration,
    LoopResult,
    StepStatus,
    TestResult,
)

if TYPE_CHECKING:

    from aat.adapters.base import AIAdapter
    from aat.core.models import Config, Scenario, StepResult
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
    """

    def __init__(
        self,
        config: Config,
        executor: StepExecutor,
        adapter: AIAdapter,
        reporter: BaseReporter,
        engine: BaseEngine,
        approval_callback: Callable[[str], bool] | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._adapter = adapter
        self._reporter = reporter
        self._engine = engine
        self._approval_callback = approval_callback or _default_prompt_approval

    async def run(self, scenarios: list[Scenario]) -> LoopResult:
        """Run the DevQA loop.

        Args:
            scenarios: Test scenarios to execute.

        Returns:
            LoopResult with iteration history.
        """
        loop_start = time.monotonic()
        iterations: list[LoopIteration] = []
        max_loops = self._config.max_loops

        try:
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

                # Ask for approval
                approved = self._approval_callback(
                    f"{analysis.cause} — {analysis.suggestion}"
                )

                if not approved:
                    iterations.append(
                        LoopIteration(
                            iteration=iteration_num,
                            test_result=test_result,
                            analysis=analysis,
                            approved=False,
                        )
                    )
                    elapsed = (time.monotonic() - loop_start) * 1000
                    return LoopResult(
                        success=False,
                        total_iterations=iteration_num,
                        iterations=iterations,
                        reason="user denied fix",
                        duration_ms=elapsed,
                    )

                # Generate fix
                source_files: dict[str, str] = {}  # MVP: empty source files
                fix = await self._adapter.generate_fix(analysis, source_files)

                iterations.append(
                    LoopIteration(
                        iteration=iteration_num,
                        test_result=test_result,
                        analysis=analysis,
                        fix=fix,
                        approved=True,
                    )
                )

                await self._generate_report(test_result)

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
            await self._engine.stop()

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
        from pathlib import Path

        output_dir = Path(self._config.reports_dir)
        await self._reporter.generate(test_result, output_dir)
