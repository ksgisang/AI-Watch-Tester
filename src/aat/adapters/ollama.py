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
scenarios as a JSON array.

Each scenario must follow this EXACT format:
{"id": "SC-001", "name": "Short name", "description": "What this tests", \
"tags": ["tag1"], "steps": [...], "expected_result": []}

"expected_result" must be an array of objects (NOT strings), each with:
  {"type": "text_visible", "value": "expected text"}
Valid types: "text_visible", "text_equals", "url_contains".
Leave as empty array [] if no specific assertion is needed.

Each step MUST have "step" (integer from 1) and "description" (non-empty).

VALID ACTIONS (use ONLY these):
- "navigate" — requires "value" with URL. Example:
  {"step": 1, "action": "navigate", "value": "{{url}}/login", "description": "Go to login"}
- "find_and_click" — requires "target" with "text". Example:
  {"step": 2, "action": "find_and_click", "target": {"text": "Login"}, \
"description": "Click login", "humanize": true}
- "find_and_type" — requires "target" with "text" AND "value". Example:
  {"step": 3, "action": "find_and_type", "target": {"text": "Email"}, \
"value": "user@test.com", "description": "Enter email", "humanize": true}
- "type_text" — types into focused field. Example:
  {"step": 4, "action": "type_text", "value": "hello", "description": "Type text"}
- "press_key" — press a key. Example:
  {"step": 5, "action": "press_key", "value": "Enter", "description": "Press enter"}
- "assert" — requires "assert_type" and "expected". Example:
  {"step": 6, "action": "assert", "assert_type": "text_visible", \
"expected": [{"type": "text_visible", "value": "Welcome"}], "description": "Verify text"}
- "wait" — milliseconds. Example:
  {"step": 7, "action": "wait", "value": "2000", "description": "Wait 2s"}
- "screenshot" — capture screen. Example:
  {"step": 8, "action": "screenshot", "description": "Capture state"}

CRITICAL RULES:
- "click" is INVALID. Use "find_and_click"
- "type" is INVALID. Use "find_and_type"
- target must NOT have "role" or "url" fields. Only "text"
- Use {{url}} for base URL in navigate actions
- Do NOT include "variables" with hardcoded URLs

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
            config.api_key
            if config.api_key and config.api_key.startswith("http")
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

        # Ollama models may return {scenarios: [...]} instead of [...]
        if isinstance(data, dict):
            for key in ("scenarios", "test_scenarios", "tests", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                # Single scenario object — wrap in list
                data = [data]

        if not isinstance(data, list):
            msg = f"Expected JSON array for scenarios, got {type(data).__name__}"
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
            "format": "json",
            "stream": False,
            "options": {
                "temperature": self._temperature,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            msg = f"Cannot connect to Ollama at {self._base_url}. Is Ollama running?"
            raise AdapterError(msg) from exc
        except httpx.TimeoutException as exc:
            msg = f"Ollama timeout after 300s. Model may be too slow for this task: {exc}"
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
