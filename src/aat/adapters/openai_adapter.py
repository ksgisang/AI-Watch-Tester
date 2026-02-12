"""OpenAIAdapter — OpenAI GPT API integration."""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

from aat.adapters.base import AIAdapter
from aat.core.exceptions import AdapterError
from aat.core.models import (
    AnalysisResult,
    FileChange,
    FixResult,
    Scenario,
    Severity,
)

if TYPE_CHECKING:
    from aat.core.models import AIConfig, TestResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates (shared with ClaudeAdapter / OllamaAdapter)
# ---------------------------------------------------------------------------

_SYSTEM_ANALYZE_FAILURE = """\
You are an expert QA engineer. Analyze the following test failure and return \
a JSON object with these fields:
- "cause": a concise description of the root cause
- "suggestion": an actionable fix suggestion
- "severity": one of "critical", "warning", "info"
- "related_files": a list of file paths likely involved

Return ONLY valid JSON, no markdown fences."""

_SYSTEM_GENERATE_FIX = """\
You are an expert software engineer. Given a failure analysis and source files, \
propose a code fix. Return a JSON object with:
- "description": short description of the fix
- "files_changed": list of objects with "path", "original", "modified", "description"
- "confidence": float 0.0-1.0

Return ONLY valid JSON, no markdown fences."""

_SYSTEM_GENERATE_SCENARIOS = """\
You are an expert QA engineer. Given a specification document, generate test \
scenarios as a JSON array. Each element must have:
- "id": "SC-NNN" format
- "name": short name
- "description": what the scenario tests
- "tags": list of tags
- "steps": list of step objects with "step" (int), "action", "description", \
and optionally "value", "target"
- "expected_result": list of expected result objects (can be empty)
- "variables": dict of variables (can be empty)

For steps, valid actions include: navigate, find_and_click, find_and_type, \
type_text, press_key, assert, wait, screenshot.

Return ONLY a valid JSON array, no markdown fences."""

_SYSTEM_ANALYZE_DOCUMENT = """\
You are an expert QA engineer. Analyze the following document and extract:
- "screens": list of screen/page descriptions
- "elements": list of UI elements found
- "flows": list of user flows described

Return ONLY valid JSON, no markdown fences."""


class OpenAIAdapter(AIAdapter):
    """OpenAI GPT AI adapter.

    Uses the OpenAI API with vision support for image analysis.
    """

    def __init__(self, config: AIConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(api_key=config.api_key)

    # ------------------------------------------------------------------
    # AIAdapter interface
    # ------------------------------------------------------------------

    async def analyze_failure(
        self,
        test_result: TestResult,
        screenshots: list[bytes] | None = None,
    ) -> AnalysisResult:
        """Analyze test failure cause via OpenAI API."""
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Scenario: {test_result.scenario_id}"
                    f" — {test_result.scenario_name}\n"
                    f"Passed: {test_result.passed}\n"
                    f"Total steps: {test_result.total_steps}, "
                    f"Passed: {test_result.passed_steps}, "
                    f"Failed: {test_result.failed_steps}\n\n"
                    "Step details:\n"
                    + "\n".join(
                        f"  Step {s.step}: {s.status.value} — {s.description}"
                        + (f" (error: {s.error_message})" if s.error_message else "")
                        for s in test_result.steps
                    )
                ),
            },
        ]

        if screenshots:
            for img_bytes in screenshots:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:image/png;base64,"
                                f"{base64.b64encode(img_bytes).decode()}"
                            ),
                        },
                    }
                )

        data = await self._call_api(_SYSTEM_ANALYZE_FAILURE, user_content)

        try:
            return AnalysisResult(
                cause=str(data["cause"]),
                suggestion=str(data["suggestion"]),
                severity=Severity(data["severity"]),
                related_files=[str(f) for f in data.get("related_files", [])],
            )
        except (KeyError, ValueError) as exc:
            msg = f"Failed to parse analysis response: {exc}"
            raise AdapterError(msg) from exc

    async def generate_fix(
        self,
        analysis: AnalysisResult,
        source_files: dict[str, str],
    ) -> FixResult:
        """Generate code fix based on analysis."""
        source_section = "\n\n".join(
            f"--- {path} ---\n{content}" for path, content in source_files.items()
        )
        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Analysis:\n"
                    f"  Cause: {analysis.cause}\n"
                    f"  Suggestion: {analysis.suggestion}\n"
                    f"  Severity: {analysis.severity.value}\n"
                    f"  Related files: {', '.join(analysis.related_files)}\n\n"
                    f"Source files:\n{source_section}"
                ),
            },
        ]

        data = await self._call_api(_SYSTEM_GENERATE_FIX, user_content)

        try:
            files_changed = [
                FileChange(
                    path=str(fc["path"]),
                    original=str(fc["original"]),
                    modified=str(fc["modified"]),
                    description=str(fc.get("description", "")),
                )
                for fc in data["files_changed"]
            ]
            return FixResult(
                description=str(data["description"]),
                files_changed=files_changed,
                confidence=float(data["confidence"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            msg = f"Failed to parse fix response: {exc}"
            raise AdapterError(msg) from exc

    async def generate_scenarios(
        self,
        document_text: str,
        images: list[bytes] | None = None,
    ) -> list[Scenario]:
        """Generate test scenarios from document text."""
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": document_text},
        ]

        if images:
            for img_bytes in images:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:image/png;base64,"
                                f"{base64.b64encode(img_bytes).decode()}"
                            ),
                        },
                    }
                )

        data = await self._call_api(_SYSTEM_GENERATE_SCENARIOS, user_content)

        if not isinstance(data, list):
            msg = "Expected JSON array for scenarios"
            raise AdapterError(msg)

        try:
            return [Scenario.model_validate(s) for s in data]
        except Exception as exc:
            msg = f"Failed to parse scenarios response: {exc}"
            raise AdapterError(msg) from exc

    async def analyze_document(
        self,
        document_text: str,
        images: list[bytes] | None = None,
    ) -> dict[str, Any]:
        """Analyze spec document to extract screens/elements/flows."""
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": document_text},
        ]

        if images:
            for img_bytes in images:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:image/png;base64,"
                                f"{base64.b64encode(img_bytes).decode()}"
                            ),
                        },
                    }
                )

        data = await self._call_api(_SYSTEM_ANALYZE_DOCUMENT, user_content)

        if not isinstance(data, dict):
            msg = "Expected JSON object for document analysis"
            raise AdapterError(msg)

        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        system_prompt: str,
        user_content: list[dict[str, Any]],
    ) -> Any:
        """Call OpenAI Chat Completions API and parse JSON response.

        Args:
            system_prompt: System message.
            user_content: User message content blocks.

        Returns:
            Parsed JSON data.

        Raises:
            AdapterError: On API or parse failure.
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
        except Exception as exc:
            msg = f"OpenAI API call failed: {exc}"
            raise AdapterError(msg) from exc

        choice = response.choices[0]
        raw_text = choice.message.content or ""

        if not raw_text:
            msg = "Empty response from OpenAI"
            raise AdapterError(msg)

        # Strip markdown fences if the model wraps JSON in ```json ... ```
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            msg = (
                f"Failed to parse JSON from OpenAI response: {exc}\n"
                f"Raw: {raw_text[:500]}"
            )
            raise AdapterError(msg) from exc
