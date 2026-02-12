"""OllamaAdapter — Local Ollama LLM integration."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

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
# Prompt templates (same as ClaudeAdapter)
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

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaAdapter(AIAdapter):
    """Local Ollama LLM adapter.

    Uses Ollama's HTTP API for text-based AI tasks.
    Note: Most local models don't support vision, so images are skipped.
    """

    def __init__(self, config: AIConfig) -> None:
        self._config = config
        # Use api_key field as base_url override, or default to localhost
        self._base_url = (
            config.api_key if config.api_key and config.api_key.startswith("http")
            else _DEFAULT_OLLAMA_URL
        )
        self._model = config.model
        self._temperature = config.temperature

    async def analyze_failure(
        self,
        test_result: TestResult,
        screenshots: list[bytes] | None = None,
    ) -> AnalysisResult:
        """Analyze test failure cause via Ollama."""
        if screenshots:
            logger.info(
                "OllamaAdapter: ignoring %d screenshots (text-only model)",
                len(screenshots),
            )

        user_text = (
            f"Scenario: {test_result.scenario_id} — {test_result.scenario_name}\n"
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
        )

        data = await self._call_api(_SYSTEM_ANALYZE_FAILURE, user_text)

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
        user_text = (
            f"Analysis:\n"
            f"  Cause: {analysis.cause}\n"
            f"  Suggestion: {analysis.suggestion}\n"
            f"  Severity: {analysis.severity.value}\n"
            f"  Related files: {', '.join(analysis.related_files)}\n\n"
            f"Source files:\n{source_section}"
        )

        data = await self._call_api(_SYSTEM_GENERATE_FIX, user_text)

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
        if images:
            logger.info("OllamaAdapter: ignoring %d images (text-only model)", len(images))

        data = await self._call_api(_SYSTEM_GENERATE_SCENARIOS, document_text)

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
        if images:
            logger.info("OllamaAdapter: ignoring %d images (text-only model)", len(images))

        data = await self._call_api(_SYSTEM_ANALYZE_DOCUMENT, document_text)

        if not isinstance(data, dict):
            msg = "Expected JSON object for document analysis"
            raise AdapterError(msg)

        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_api(self, system_prompt: str, user_text: str) -> Any:
        """Call Ollama chat API and parse JSON response.

        Args:
            system_prompt: System message.
            user_text: User message text.

        Returns:
            Parsed JSON data.

        Raises:
            AdapterError: On API or parse failure.
        """
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "options": {
                "temperature": self._temperature,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            msg = f"Cannot connect to Ollama at {self._base_url}. Is Ollama running?"
            raise AdapterError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"Ollama API error: {exc.response.status_code} — {exc.response.text[:300]}"
            raise AdapterError(msg) from exc
        except httpx.HTTPError as exc:
            msg = f"Ollama HTTP error: {exc}"
            raise AdapterError(msg) from exc

        try:
            resp_data = response.json()
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse Ollama response as JSON: {exc}"
            raise AdapterError(msg) from exc

        raw_text = resp_data.get("message", {}).get("content", "")
        if not raw_text:
            msg = "Empty response from Ollama"
            raise AdapterError(msg)

        # Strip markdown fences if the model wraps JSON in ```json ... ```
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            msg = f"Failed to parse JSON from Ollama response: {exc}\nRaw: {raw_text[:500]}"
            raise AdapterError(msg) from exc
