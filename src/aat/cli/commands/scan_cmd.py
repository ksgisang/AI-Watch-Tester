"""aat scan — pre-scan a URL to collect element data for scenario authoring."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import typer

from aat.core.config import load_config
from aat.core.exceptions import AATError


def scan_command(
    url: str = typer.Option(..., "--url", "-u", help="URL to scan."),
    compare: str | None = typer.Option(
        None,
        "--compare",
        help="Previous scan_result.json to diff against.",
    ),
    session: str | None = typer.Option(
        None,
        "--session",
        help="Load saved session before scanning (for post-login pages).",
    ),
    config_path: str | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Scan a URL and collect UI elements (selectors, OCR text, coordinates)."""
    try:
        asyncio.run(_scan(url, compare, session, config_path))
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


async def _scan(
    url: str,
    compare_path: str | None,
    session_name: str | None,
    config_path: str | None,
) -> None:
    """Execute scan asynchronously."""
    from aat.core.models import EngineConfig
    from aat.engine.web import WebEngine

    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)

    engine_config = EngineConfig(
        type="web",
        headless=True,
        viewport_width=config.engine.viewport_width,
        viewport_height=config.engine.viewport_height,
    )
    engine = WebEngine(engine_config)

    typer.echo(f"[AWT] Scanning {url}...")
    start = time.monotonic()

    try:
        await engine.start()

        # Load session if provided (for scanning post-login pages)
        if session_name:
            session_path = Path(config.data_dir) / "sessions" / f"{session_name}.json"
            if session_path.exists():
                typer.echo(f"[AWT] Loading session: {session_name}")
                await engine.load_session(str(session_path))
            else:
                typer.echo(f"[AWT] Session '{session_name}' not found, scanning without login")

        await engine.navigate(url)

        # Wait for page to settle (longer for Flutter CanvasKit)
        await asyncio.sleep(3.0)

        page = engine.page

        # 1. Detect Flutter
        #
        # This runs *before* the screenshot on purpose. A CanvasKit app that
        # fetches its font late paints tofu boxes first and the real glyphs a
        # second later; a scan image captured ahead of that repaint is evidence
        # of nothing. Screenshot after the wait, not before it.
        from aat.engine.flutter_semantics import (
            activate_semantics,
            get_all_semantics_labels,
            wait_for_fonts,
            wait_until_flutter_ready,
        )

        # Waits for the app to boot before answering. A scan that asks too
        # early reports "not Flutter" and emits tips for the wrong platform.
        is_flutter = await wait_until_flutter_ready(page)
        if is_flutter:
            typer.echo("[AWT] Flutter CanvasKit detected — activating Semantics...")
            await activate_semantics(page)
            await wait_for_fonts(page)

            # Wait for stable Semantics node count (max 10s)
            from aat.engine.flutter_semantics import _count_semantics_nodes

            prev_count = -1
            stable_rounds = 0
            for _ in range(10):
                await asyncio.sleep(1.0)
                count = await _count_semantics_nodes(page)
                if count == prev_count and count > 0:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                prev_count = count
            typer.echo(f"[AWT] Semantics stable: {prev_count} nodes")

        # 2. Screenshot
        scan_dir = Path(config.data_dir) / "scans"
        scan_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        ss_path = scan_dir / f"scan_{ts}.png"
        ss_bytes = await engine.screenshot()
        ss_path.write_bytes(ss_bytes)

        # 3. Collect elements
        elements: list[dict[str, Any]] = []

        # 3a. DOM elements (non-Flutter or hybrid)
        dom_elements = await _collect_dom_elements(page)
        elements.extend(dom_elements)

        # 3b. Flutter Semantics elements
        if is_flutter:
            sem_elements = await _collect_semantics_elements(page)
            elements.extend(sem_elements)
            sem_labels = await get_all_semantics_labels(page)
            typer.echo(f"[AWT] Semantics labels: {len(sem_labels)}")

        # 3c. OCR elements
        ocr_elements = await _collect_ocr_elements(ss_bytes)
        # Deduplicate: skip OCR results that overlap with DOM/Semantics
        for ocr_el in ocr_elements:
            if not _is_duplicate(ocr_el, elements):
                elements.append(ocr_el)

        # 4. Build result
        elapsed = (time.monotonic() - start) * 1000
        result = {
            "url": url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "screenshot": str(ss_path),
            "is_flutter": is_flutter,
            "viewport": {
                "width": engine_config.viewport_width,
                "height": engine_config.viewport_height,
            },
            "elements": elements,
            "element_count": len(elements),
            "elapsed_ms": round(elapsed, 0),
        }

        # 5. Save
        out_path = Path(config.data_dir) / "scan_result.json"
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        typer.echo(f"[AWT] Found {len(elements)} elements in {elapsed:.0f}ms")
        typer.echo(f"[AWT] Screenshot: {ss_path}")
        typer.echo(f"[AWT] Result: {out_path}")

        # 6. Compare if requested
        if compare_path:
            _compare_scans(out_path, Path(compare_path))

    finally:
        await engine.stop()


# -- Element collectors -------------------------------------------------------


async def _collect_dom_elements(page: Any) -> list[dict[str, Any]]:
    """Collect clickable/interactive DOM elements with bounding boxes."""
    try:
        elements: list[dict[str, Any]] = await page.evaluate("""() => {
            const results = [];
            const selectors = [
                'a', 'button', 'input', 'textarea', 'select',
                '[role="button"]', '[role="link"]', '[role="tab"]',
                '[role="menuitem"]', '[onclick]', '[tabindex]',
            ];
            const seen = new Set();

            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (seen.has(el)) continue;
                    seen.add(el);

                    const rect = el.getBoundingClientRect();
                    if (rect.width < 4 || rect.height < 4) continue;
                    if (rect.x < 0 || rect.y < 0) continue;

                    const label = (
                        el.textContent?.trim()?.substring(0, 80) ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('placeholder') ||
                        el.getAttribute('title') ||
                        ''
                    );
                    if (!label) continue;

                    results.push({
                        label: label,
                        type: el.tagName.toLowerCase(),
                        input_type: el.getAttribute('type') || '',
                        role: el.getAttribute('role') || '',
                        selector: _bestSelector(el),
                        x: Math.round(rect.x + rect.width / 2),
                        y: Math.round(rect.y + rect.height / 2),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        source: 'dom',
                    });
                }
            }

            function _bestSelector(el) {
                if (el.id) return '#' + el.id;
                if (el.className && typeof el.className === 'string') {
                    const cls = el.className.trim().split(/\\s+/)[0];
                    if (cls) return el.tagName.toLowerCase() + '.' + cls;
                }
                return el.tagName.toLowerCase();
            }

            return results;
        }""")
        return elements  # type: ignore[return-value]
    except Exception:
        return []


async def _collect_semantics_elements(page: Any) -> list[dict[str, Any]]:
    """Collect Flutter Semantics elements with bounding boxes (shadow DOM aware)."""
    try:
        elements: list[dict[str, Any]] = await page.evaluate("""() => {
            const results = [];

            // Collect from all possible locations (direct + shadow DOM)
            let nodes = document.querySelectorAll('flt-semantics');

            // Flutter 3.x: flutter-view shadow DOM
            if (nodes.length === 0) {
                const fv = document.querySelector('flutter-view');
                if (fv && fv.shadowRoot) {
                    nodes = fv.shadowRoot.querySelectorAll('flt-semantics');
                }
            }

            // Flutter 2.x: flt-glass-pane shadow DOM
            if (nodes.length === 0) {
                const gp = document.querySelector('flt-glass-pane');
                if (gp && gp.shadowRoot) {
                    nodes = gp.shadowRoot.querySelectorAll('flt-semantics');
                }
            }

            for (const node of nodes) {
                const label = node.getAttribute('aria-label');
                if (!label) continue;

                const rect = node.getBoundingClientRect();
                if (rect.width < 2 || rect.height < 2) continue;

                results.push({
                    label: label,
                    type: node.getAttribute('role') || 'semantics',
                    role: node.getAttribute('role') || '',
                    selector: 'flt-semantics[aria-label="'
                        + label.replace(/"/g, '\\\\"') + '"]',
                    x: Math.round(rect.x + rect.width / 2),
                    y: Math.round(rect.y + rect.height / 2),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    source: 'semantics',
                });
            }
            return results;
        }""")
        return elements  # type: ignore[return-value]
    except Exception:
        return []


async def _collect_ocr_elements(
    screenshot: bytes,
) -> list[dict[str, Any]]:
    """Collect text elements via OCR."""
    try:
        import cv2
        import numpy as np
        import pytesseract  # type: ignore[import-untyped]

        arr = np.frombuffer(screenshot, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []

        # Preprocess
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        img = clahe.apply(img)
        h, w = img.shape
        img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        data = pytesseract.image_to_data(
            img,
            lang="eng+kor",
            config="--oem 3",
            output_type=pytesseract.Output.DICT,
        )

        elements: list[dict[str, Any]] = []
        n = len(data.get("text", []))
        for i in range(n):
            conf = data["conf"][i]
            if not isinstance(conf, (int, float)) or conf <= 30:
                continue
            text = str(data["text"][i]).strip()
            if len(text) < 2:
                continue

            # 2x upscale → original coords
            left = int(data["left"][i]) // 2
            top = int(data["top"][i]) // 2
            wd = int(data["width"][i]) // 2
            ht = int(data["height"][i]) // 2

            elements.append(
                {
                    "label": text,
                    "type": "text",
                    "role": "",
                    "selector": "",
                    "x": left + wd // 2,
                    "y": top + ht // 2,
                    "width": wd,
                    "height": ht,
                    "source": "ocr",
                    "confidence": round(float(conf) / 100, 2),
                }
            )

        return elements
    except Exception:
        return []


def _is_duplicate(
    ocr_el: dict[str, Any],
    existing: list[dict[str, Any]],
    distance: int = 30,
) -> bool:
    """Check if OCR element overlaps with an existing element."""
    ox, oy = ocr_el["x"], ocr_el["y"]
    return any(abs(el["x"] - ox) < distance and abs(el["y"] - oy) < distance for el in existing)


# -- Compare scans -----------------------------------------------------------


def _compare_scans(current_path: Path, previous_path: Path) -> None:
    """Compare two scan results and output differences."""
    try:
        current = json.loads(current_path.read_text("utf-8"))
        previous = json.loads(previous_path.read_text("utf-8"))
    except Exception as e:
        typer.echo(f"[AWT] Compare failed: {e}")
        return

    prev_map = {el["label"]: el for el in previous.get("elements", [])}
    curr_map = {el["label"]: el for el in current.get("elements", [])}

    added = [k for k in curr_map if k not in prev_map]
    removed = [k for k in prev_map if k not in curr_map]
    moved = []
    for label in curr_map:
        if label in prev_map:
            c, p = curr_map[label], prev_map[label]
            if abs(c["x"] - p["x"]) > 10 or abs(c["y"] - p["y"]) > 10:
                moved.append((label, p, c))

    if not added and not removed and not moved:
        typer.echo("[AWT] No changes detected.")
        return

    typer.echo("")
    typer.echo("=== AWT SCAN DIFF ===")
    for label in added:
        el = curr_map[label]
        typer.echo(f'  + NEW: "{label}" at ({el["x"]}, {el["y"]})')
    for label in removed:
        el = prev_map[label]
        typer.echo(f'  - REMOVED: "{label}" was at ({el["x"]}, {el["y"]})')
    for label, prev, curr in moved:
        typer.echo(f'  ~ MOVED: "{label}" ({prev["x"]},{prev["y"]}) → ({curr["x"]},{curr["y"]})')
    typer.echo(f"  Total: +{len(added)} -{len(removed)} ~{len(moved)}")
    typer.echo("=====================")
    typer.echo("")
