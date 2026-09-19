"""PDFReporter — print the report through the browser AWT already drives.

There is no PDF library here on purpose. Chromium is installed because it is
what runs the tests, and Chromium can print: the result is rendered as HTML and
handed to `page.pdf()`. That keeps the dependency list where it is and makes the
printed page match what a browser shows.

Screenshots are embedded in the file rather than linked, so the PDF can be sent
to someone who does not have the run directory.
"""

from __future__ import annotations

import base64
from pathlib import Path  # noqa: TC003
from typing import Literal

from jinja2 import Environment

from aat.core.exceptions import ReporterError
from aat.core.models import LoopResult, StepResult, StepStatus, TestResult
from aat.reporters.base import BaseReporter

ScreenshotPolicy = Literal["failures", "all", "none"]
"""Which steps bring their screenshots into the file.

`failures` covers failed, errored and warned steps — the ones a reader needs to
see. `all` is for a visual walkthrough and makes a much larger file.
"""

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_TONE_BY_STATUS = {
    StepStatus.PASSED: "pass",
    StepStatus.WARNING: "warn",
    StepStatus.FAILED: "fail",
    StepStatus.ERROR: "fail",
    StepStatus.SKIPPED: "skip",
}

_WARNING_NOTE = (
    "A step marked WARNING ran without raising an error but changed nothing on "
    "screen. A click that moves nothing has almost certainly missed its target, "
    "so read it as a failure until the screenshots for that step say otherwise."
)

_STYLE = """
/* Margins belong to the print call, not here: declaring them in both places
   lays the page out for one width and prints it at another, which pushes the
   right-hand column off the sheet. */
@page { size: A4; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Helvetica Neue", "Noto Sans KR", sans-serif;
  color: #1f2933; font-size: 10.5pt; line-height: 1.5; margin: 0;
}
h1 { font-size: 18pt; margin: 0 0 2mm; }
h2 { font-size: 13pt; margin: 8mm 0 2mm; padding-bottom: 1mm;
     border-bottom: 1px solid #d7dde3; }
h3 { font-size: 11pt; margin: 5mm 0 1.5mm; }
.sub { color: #62707d; margin: 0 0 4mm; }
.chip { display: inline-block; padding: 0.6mm 2.4mm; border-radius: 2mm;
        font-size: 8.5pt; font-weight: 600; letter-spacing: 0.02em; }
.chip.pass { background: #def7e5; color: #1b6b3a; }
.chip.warn { background: #fdf0d0; color: #8a5a00; }
.chip.fail { background: #fbdedb; color: #96231a; }
.chip.skip { background: #e7ebef; color: #52606d; }
.meta { width: 100%; border-collapse: collapse; margin-bottom: 4mm; }
.meta td { padding: 1mm 0; vertical-align: top; }
.meta td:first-child { width: 32mm; color: #62707d; }
.cards { display: flex; gap: 3mm; margin: 0 0 4mm; }
.card { flex: 1; border: 1px solid #d7dde3; border-radius: 2mm; padding: 2.5mm 3mm; }
.card .n { font-size: 16pt; font-weight: 600; }
.card .l { font-size: 8.5pt; color: #62707d; text-transform: uppercase;
           letter-spacing: 0.04em; }
.card.pass .n { color: #1b6b3a; }
.card.warn .n { color: #8a5a00; }
.card.fail .n { color: #96231a; }
.note { border-left: 3px solid #e0a72a; background: #fdf8ec; padding: 2.5mm 3mm;
        margin: 0 0 4mm; font-size: 9.5pt; }
table.steps { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
table.steps th { text-align: left; background: #f3f5f7; color: #52606d;
                 font-size: 8.5pt; text-transform: uppercase;
                 letter-spacing: 0.04em; padding: 1.5mm 2mm; }
table.steps td { padding: 1.5mm 2mm; border-bottom: 1px solid #e7ebef;
                 vertical-align: top; }
table.steps td.num, table.steps td.ms { white-space: nowrap; }
table.steps tr { page-break-inside: avoid; }
.err { color: #96231a; font-size: 9pt; display: block; margin-top: 0.8mm; }
.shot { page-break-inside: avoid; margin: 0 0 4mm; }
.shot img { width: 100%; border: 1px solid #d7dde3; border-radius: 1.5mm; }
.shot .cap { font-size: 9pt; color: #62707d; margin: 1mm 0 0; }
.kv { font-size: 9.5pt; margin: 0 0 1mm; }
.kv b { color: #52606d; font-weight: 600; }
.iter { page-break-inside: avoid; }
footer { margin-top: 8mm; padding-top: 2mm; border-top: 1px solid #e7ebef;
         font-size: 8.5pt; color: #8a97a3; }
"""

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ title }}</title>
<style>{{ style }}</style></head>
<body>
<h1>{{ title }}</h1>
<p class="sub">{{ subtitle }} &middot;
  <span class="chip {{ status_tone }}">{{ status_label }}</span></p>

<table class="meta">
  {% for label, value in meta %}
  <tr><td>{{ label }}</td><td>{{ value }}</td></tr>
  {% endfor %}
</table>

<div class="cards">
  {% for card in cards %}
  <div class="card {{ card.tone }}"><div class="n">{{ card.value }}</div>
    <div class="l">{{ card.label }}</div></div>
  {% endfor %}
</div>

{% if note %}<p class="note">{{ note }}</p>{% endif %}

{% macro steptable(steps) %}
<table class="steps">
  <thead><tr><th>#</th><th>Action</th><th>Status</th><th>Description</th>
    <th>Time</th></tr></thead>
  <tbody>
  {% for s in steps %}
    <tr>
      <td class="num">{{ s.step }}</td>
      <td>{{ s.action }}</td>
      <td><span class="chip {{ s.tone }}">{{ s.status }}</span></td>
      <td>{{ s.description }}{% if s.error %}<span class="err">{{ s.error }}</span>{% endif %}</td>
      <td class="ms">{{ s.duration }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endmacro %}

{% macro gallery(shots) %}
{% for shot in shots %}
<div class="shot"><img src="{{ shot.src }}" alt="{{ shot.caption }}">
  <p class="cap">{{ shot.caption }}</p></div>
{% endfor %}
{% endmacro %}

{% for section in sections %}
  {% if section.heading %}<h2>{{ section.heading }}</h2>{% endif %}
  <div class="iter">
  {% for line in section.lines %}<p class="kv"><b>{{ line[0] }}</b> {{ line[1] }}</p>{% endfor %}
  </div>
  {{ steptable(section.steps) }}
  {% for block in section.blocks %}
    <h3>{{ block.heading }}</h3>
    {% for line in block.lines %}<p class="kv"><b>{{ line[0] }}</b> {{ line[1] }}</p>{% endfor %}
  {% endfor %}
  {% if section.shots %}
    <h3>Screenshots</h3>
    {{ gallery(section.shots) }}
  {% endif %}
{% endfor %}

<footer>Generated by AWT (AI Watch Tester)</footer>
</body></html>
"""


class PDFReporter(BaseReporter):
    """Render a result as HTML and let Chromium print it to PDF."""

    def __init__(self, *, screenshots: ScreenshotPolicy = "failures") -> None:
        self._screenshots: ScreenshotPolicy = screenshots
        self._env = Environment(autoescape=True)

    @property
    def format_name(self) -> str:
        """Report format name."""
        return "pdf"

    async def generate(
        self,
        result: TestResult | LoopResult,
        output_dir: Path,
    ) -> Path:
        """Write report.html and report.pdf into output_dir.

        Returns:
            Path to report.pdf.
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            html_path = output_dir / "report.html"
            html_path.write_text(self.render_html(result), encoding="utf-8")
            pdf_path = output_dir / "report.pdf"
            await self._print(html_path, pdf_path)
            return pdf_path
        except ReporterError:
            raise
        except Exception as exc:
            msg = f"PDF report generation failed: {exc}"
            raise ReporterError(msg) from exc

    def render_html(self, result: TestResult | LoopResult) -> str:
        """Render the printable HTML for a result.

        Exposed on its own because the HTML is what carries the content; the
        printing step only turns it into pages.
        """
        context = (
            self._loop_context(result)
            if isinstance(result, LoopResult)
            else self._test_context(result)
        )
        return self._env.from_string(_TEMPLATE).render(style=_STYLE, **context)

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    def _test_context(self, result: TestResult) -> dict[str, object]:
        """Build the template context for a single scenario run."""
        warned = self._count_warned(result.steps)
        # A run with warnings is not a pass on the cover either: that banner is
        # what a reader remembers, so it must not say the opposite of the table.
        if not result.passed:
            status_label, status_tone = "FAIL", "fail"
        elif warned:
            status_label, status_tone = "PASS WITH WARNINGS", "warn"
        else:
            status_label, status_tone = "PASS", "pass"

        return {
            "title": f"Test Report: {result.scenario_name}",
            "subtitle": result.scenario_id,
            "status_label": status_label,
            "status_tone": status_tone,
            "meta": [
                ("Scenario ID", result.scenario_id),
                ("Run at", result.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
                ("Duration", f"{result.duration_ms:.0f} ms"),
            ],
            "cards": self._cards(result, warned),
            "note": _WARNING_NOTE if warned else None,
            "sections": [
                {
                    "heading": "Steps",
                    "lines": [],
                    "steps": [self._step_row(s) for s in result.steps],
                    "blocks": [],
                    "shots": self._gallery(result.steps),
                }
            ],
        }

    def _loop_context(self, result: LoopResult) -> dict[str, object]:
        """Build the template context for a DevQA loop run."""
        warned = sum(self._count_warned(it.test_result.steps) for it in result.iterations)
        meta = [
            ("Run at", result.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
            ("Iterations", str(result.total_iterations)),
            ("Duration", f"{result.duration_ms:.0f} ms"),
        ]
        if result.reason:
            meta.append(("Reason", result.reason))

        sections = []
        for iteration in result.iterations:
            test_result = iteration.test_result
            blocks = []
            if iteration.analysis:
                blocks.append(
                    {
                        "heading": "Analysis",
                        "lines": [
                            ("Cause:", iteration.analysis.cause),
                            ("Suggestion:", iteration.analysis.suggestion),
                            ("Severity:", iteration.analysis.severity.value),
                        ],
                    }
                )
            if iteration.fix:
                changed = ", ".join(fc.path for fc in iteration.fix.files_changed)
                blocks.append(
                    {
                        "heading": "Fix Applied",
                        "lines": [
                            ("Description:", iteration.fix.description),
                            ("Confidence:", f"{iteration.fix.confidence:.0%}"),
                            ("Files changed:", changed or "—"),
                        ],
                    }
                )
            if iteration.branch_name or iteration.commit_hash:
                git_lines = []
                if iteration.branch_name:
                    git_lines.append(("Branch:", iteration.branch_name))
                if iteration.commit_hash:
                    git_lines.append(("Commit:", iteration.commit_hash))
                blocks.append({"heading": "Git", "lines": git_lines})

            lines = [
                ("Scenario:", f"{test_result.scenario_id} — {test_result.scenario_name}"),
                (
                    "Steps:",
                    f"{test_result.passed_steps}/{test_result.total_steps} passed, "
                    f"{test_result.duration_ms:.0f} ms",
                ),
            ]
            if iteration.approved is not None:
                lines.append(("Approved:", "Yes" if iteration.approved else "No"))

            sections.append(
                {
                    "heading": f"Iteration {iteration.iteration}"
                    f" — {'PASS' if test_result.passed else 'FAIL'}",
                    "lines": lines,
                    "steps": [self._step_row(s) for s in test_result.steps],
                    "blocks": blocks,
                    "shots": self._gallery(test_result.steps),
                }
            )

        return {
            "title": "DevQA Loop Report",
            "subtitle": f"{result.total_iterations} iteration(s)",
            "status_label": "SUCCESS" if result.success else "FAILURE",
            "status_tone": "pass" if result.success else "fail",
            "meta": meta,
            "cards": [
                {"label": "Iterations", "value": str(result.total_iterations), "tone": ""},
                {
                    "label": "Result",
                    "value": "OK" if result.success else "Failed",
                    "tone": "pass" if result.success else "fail",
                },
                {"label": "Warnings", "value": str(warned), "tone": "warn" if warned else ""},
            ],
            "note": _WARNING_NOTE if warned else None,
            "sections": sections,
        }

    # ------------------------------------------------------------------
    # Row / card / image helpers
    # ------------------------------------------------------------------

    def _cards(self, result: TestResult, warned: int) -> list[dict[str, str]]:
        """Summary cards for a single scenario run."""
        return [
            {"label": "Steps", "value": str(result.total_steps), "tone": ""},
            {"label": "Passed", "value": str(result.passed_steps), "tone": "pass"},
            {"label": "Warnings", "value": str(warned), "tone": "warn" if warned else ""},
            {
                "label": "Failed",
                "value": str(result.failed_steps),
                "tone": "fail" if result.failed_steps else "",
            },
        ]

    def _step_row(self, step: StepResult) -> dict[str, str]:
        """One row of the step table."""
        return {
            "step": str(step.step),
            "action": step.action.value,
            "status": step.status.value.upper(),
            "tone": _TONE_BY_STATUS.get(step.status, "skip"),
            "description": step.description,
            "error": step.error_message or "",
            "duration": f"{step.elapsed_ms:.0f} ms",
        }

    def _count_warned(self, steps: list[StepResult]) -> int:
        """How many steps ran without changing anything on screen."""
        return sum(1 for s in steps if s.status == StepStatus.WARNING)

    def _gallery(self, steps: list[StepResult]) -> list[dict[str, str]]:
        """Embed the screenshots the reader needs, following the policy."""
        if self._screenshots == "none":
            return []

        shots: list[dict[str, str]] = []
        for step in steps:
            if self._screenshots == "failures" and _TONE_BY_STATUS.get(step.status) not in (
                "fail",
                "warn",
            ):
                continue
            for when, path in (
                ("before", step.screenshot_before),
                ("after", step.screenshot_after),
            ):
                src = self._data_uri(path)
                if src:
                    shots.append(
                        {
                            "src": src,
                            "caption": f"Step {step.step} · {when} · {step.description}",
                        }
                    )
        return shots

    def _data_uri(self, path: str | None) -> str:
        """Read an image into the document, or give up quietly.

        A screenshot that was moved or never taken must not cost us the whole
        report, so a missing file just leaves its slot out.
        """
        if not path:
            return ""
        image = Path(path)
        mime = _MIME_BY_SUFFIX.get(image.suffix.lower())
        if mime is None:
            return ""
        try:
            raw = image.read_bytes()
        except OSError:
            return ""
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------

    async def _print(self, html_path: Path, pdf_path: Path) -> None:
        """Print the rendered HTML with Chromium."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - playwright is a hard dependency
            msg = (
                "Playwright is what prints the PDF, and it is not importable: "
                f"{exc}. Install it with `pip install playwright`."
            )
            raise ReporterError(msg) from exc

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    # Resolve before asking for a URI: a relative path raises
                    # rather than converting, and reports_dir defaults to the
                    # relative "reports", so the default configuration would
                    # write the HTML and then fail to print it.
                    await page.goto(html_path.resolve().as_uri(), wait_until="load")
                    await page.pdf(
                        path=str(pdf_path),
                        format="A4",
                        print_background=True,
                        margin={
                            "top": "14mm",
                            "bottom": "14mm",
                            "left": "12mm",
                            "right": "12mm",
                        },
                    )
                finally:
                    await browser.close()
        except Exception as exc:
            msg = (
                f"Could not print the report to PDF: {exc}. "
                "Chromium does the printing — `playwright install chromium` if it "
                f"is missing. The HTML is readable as it is at {html_path}."
            )
            raise ReporterError(msg) from exc
