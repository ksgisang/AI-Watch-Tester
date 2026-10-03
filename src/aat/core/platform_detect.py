"""Platform detection — identify frontend framework from page source.

Detects Flutter Web, React, Next.js, Vue, Angular, Svelte, etc.
from DOM markers, script tags, and meta elements.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# -- Detection rules -------------------------------------------------------
# Each rule: (platform_key, display_name, list of DOM markers)
# A platform is detected if ANY marker is found in the page source.

_DETECTION_RULES: list[tuple[str, str, list[str]]] = [
    (
        "flutter_canvaskit",
        "Flutter Web (CanvasKit)",
        ["flt-glass-pane", "flutter.js", "canvaskit.js", "flutter_service_worker"],
    ),
    (
        "flutter_html",
        "Flutter Web (HTML renderer)",
        ["flt-glass-pane", "flutter.js"],
    ),
    (
        "nextjs",
        "Next.js (React)",
        ["__next", "_next/static", "__NEXT_DATA__"],
    ),
    (
        "react_spa",
        "React SPA",
        ["react-root", "_reactRootContainer", "data-reactroot"],
    ),
    (
        "vue_spa",
        "Vue SPA",
        ["data-v-", "__vue_app__", "vue-app"],
    ),
    (
        "angular",
        "Angular",
        ["ng-version", "_nghost", "ng-app"],
    ),
    (
        "svelte",
        "Svelte/SvelteKit",
        ["svelte-", "__sveltekit", "data-sveltekit"],
    ),
]

# -- Built-in platform tips ------------------------------------------------

_BUILTIN_TIPS: dict[str, list[str]] = {
    "flutter_canvaskit": [
        # This used to read "Use click_at + type_text instead of
        # find_and_type (hidden inputs)". Measured against a real CanvasKit
        # app (ClasRing, 2026-10-03): find_and_type reached every field,
        # logged in with real credentials, and drove four admin screens --
        # 23/23 steps. The advice was steering users away from the path that
        # works and toward hand-tuned coordinates that break on any reflow.
        "Use find_and_click / find_and_type with target.text — "
        "AWT activates Flutter's Semantics tree and matches its labels",
        "target.text must match the Semantics label, which is often the "
        "field's floating label (e.g. '이메일'), not its hint text",
        "text_visible falls back to OCR when the text lives only on canvas",
        "Avoid CSS selectors — Flutter doesn't use standard DOM elements",
        "Fonts can arrive after first paint; AWT waits for them before "
        "capturing, but add a wait step if your app loads data on startup",
    ],
    "flutter_html": [
        "HTML renderer has better DOM access than CanvasKit",
        "find_and_type may work but verify with screenshots",
        "Prefer text-based matching over selectors",
    ],
    "nextjs": [
        "Wait for hydration: add wait step after navigate",
        "Server-rendered text is available immediately in DOM",
        "Client-side navigation may not trigger full page load",
    ],
    "react_spa": [
        "Components may render asynchronously — add wait steps",
        "Use data-testid selectors when available",
        "React portals (modals) may render outside root element",
    ],
    "vue_spa": [
        "Vue transitions may delay element visibility",
        "Use data-test or data-cy selectors when available",
    ],
    "angular": [
        "Angular change detection may delay DOM updates",
        "Use data-test attributes for stable selectors",
    ],
    "svelte": [
        "Svelte compiles to vanilla DOM — selectors work well",
        "SvelteKit may have server/client rendering differences",
    ],
}


async def detect_platform(engine: object) -> dict[str, Any]:
    """Detect frontend platform from current page.

    Args:
        engine: BaseEngine with get_page_text() and page attribute.

    Returns:
        {
            "platform": "flutter_canvaskit",
            "display": "Flutter Web (CanvasKit)",
            "tips": [...],
            "markers_found": [...]
        }
        or {"platform": "unknown", ...} if not detected.
    """
    page_source = ""
    try:
        if hasattr(engine, "page"):
            page_source = await engine.page.content()
        elif hasattr(engine, "get_page_text"):
            page_source = await engine.get_page_text()
    except Exception:
        pass

    if not page_source:
        return {
            "platform": "unknown",
            "display": "Unknown",
            "tips": [],
            "markers_found": [],
        }

    page_lower = page_source.lower()

    for key, display, markers in _DETECTION_RULES:
        found = [m for m in markers if m.lower() in page_lower]
        if found:
            tips = _BUILTIN_TIPS.get(key, [])
            logger.info("Platform detected: %s (markers: %s)", display, found)
            return {
                "platform": key,
                "display": display,
                "tips": tips,
                "markers_found": found,
            }

    return {
        "platform": "unknown",
        "display": "Unknown",
        "tips": [],
        "markers_found": [],
    }


def format_platform_info(info: dict[str, Any]) -> str:
    """Format platform detection result for CLI output."""
    if info["platform"] == "unknown":
        return ""

    lines = [
        f"  🔍 Detected: {info['display']}",
    ]
    for tip in info.get("tips", []):
        lines.append(f"    ⚠️  {tip}")
    return "\n".join(lines)
