"""Where AWT banks a picture of every element it has successfully found.

This is the half of self-healing that nobody could see. The idea is simple:
when a step finds its element through the DOM, crop that element out of the
screenshot and keep it. When the selector later breaks -- a class is renamed, a
wrapper div appears, the framework regenerates its hashes -- the saved picture
is still a true description of what the user is looking for, so the run can
heal instead of failing.

It did not work, for four separate reasons, and this module exists to remove
two of them:

* **Nothing was ever banked.** The only writer lived inside
  ``HybridMatcher``, which the step executor reaches *only after* a DOM lookup
  has already failed. Elements that were found -- the overwhelming majority --
  were never photographed. A store that is only written when matching fails
  has nothing to offer when matching fails.
* **The store was global, unbounded and shared with the test suite.** The
  directory was hardcoded to ``~/.awt/templates``, so unit tests wrote into the
  developer's real home: 107 of the 109 files found there were byte-identical
  fixtures from ``tests/``. Worse, the key was ``md5(target_name)``, with no
  notion of *which site* -- so ``"확인"`` on two unrelated applications was one
  entry, and whichever ran last won.

So: the directory is resolved at call time and overridable, entries are scoped
to a host, and every entry carries enough metadata to be listed and expired.

Scoping by host is a deliberate trade. It means a template banked against
``localhost:3000`` will not heal a run against ``app.example.com``, even when
they are the same application in two environments. The alternative is worse:
one application's picture answering another application's lookup is a wrong
click, and a wrong click that *passes* is the failure mode AAT-109 exists to
prevent. Losing a heal is recoverable; reporting a false pass is not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import cv2
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator

    from aat.core.models import TargetSpec

logger = logging.getLogger(__name__)

#: Environment variable that relocates the whole store. Read on every call
#: rather than captured at import, so a test (or a user with a shared home
#: directory) can redirect it without reloading the module.
ENV_DIR = "AWT_TEMPLATES_DIR"

#: Fallback when a URL yields no host -- ``file://`` pages, ``about:blank``,
#: and the desktop engine, which has no URL at all.
UNSCOPED = "_unscoped"

#: Default retention. A template older than this describes a UI that has had a
#: month to change; healing from it is a guess dressed as evidence.
MAX_AGE_DAYS = 30

#: Per-host ceiling, oldest evicted first. A long suite against one host banks
#: one entry per distinct target, so this is generous for real scenarios and
#: still bounds a runaway loop.
MAX_PER_SCOPE = 300

#: Padding around the element, in screenshot pixels. Enough to carry a border
#: or focus ring, which is often what distinguishes two sibling buttons.
PAD = 5

#: Below this, a crop is too small to match reliably.
MIN_SIDE = 8

_SAFE_SCOPE = re.compile(r"[^a-z0-9.\-]+")


@dataclass(frozen=True)
class TemplateEntry:
    """One banked picture, as reported by :func:`inventory`."""

    scope: str
    key: str
    target: str
    method: str
    confidence: float
    width: int
    height: int
    saved_at: float
    path: Path

    @property
    def age_days(self) -> float:
        return max(0.0, (time.time() - self.saved_at) / 86400.0)


def templates_root() -> Path:
    """The directory the store lives in, resolved now rather than at import."""
    override = os.environ.get(ENV_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".awt" / "templates"


def scope_for(url: str | None) -> str:
    """Reduce a page URL to the host the templates belong to.

    Port is kept: ``localhost:3000`` and ``localhost:8080`` are routinely two
    different applications on one developer's machine.
    """
    if not url:
        return UNSCOPED
    try:
        parsed = urlparse(url)
    except ValueError:
        return UNSCOPED
    host = (parsed.netloc or "").lower()
    if not host:
        return UNSCOPED
    return scope_for_host(host)


def scope_for_host(host: str | None) -> str:
    """Scope name for a bare host, as a user would type it on the CLI."""
    if not host:
        return UNSCOPED
    cleaned = _SAFE_SCOPE.sub("_", host.lower()).strip("_.")
    return cleaned or UNSCOPED


def name_for(target: TargetSpec | None) -> str:
    """The name a target's picture is filed under, for writers and readers alike.

    Both sides have to agree or the store is write-only. They did not: the
    executor banked under ``text or selector`` while the chain looked up
    ``text or image``, so a step identified **only by a selector** -- exactly
    the step that self-healing exists for, since a renamed selector is the
    failure being healed -- banked a picture that nothing could ever find.

    ``text`` comes first because it is the more durable name. A caption
    survives the class rename that broke the selector in the first place.
    """
    if target is None:
        return ""
    return target.text or target.selector or target.image or ""


def key_for(target_name: str) -> str:
    """Stable short key for a target's name."""
    return hashlib.md5(target_name.encode("utf-8")).hexdigest()[:12]  # noqa: S324


def path_for(scope: str, target_name: str) -> Path:
    """Where the picture for this target on this host would live."""
    return templates_root() / scope / f"{key_for(target_name)}.png"


def lookup(scope: str, target_name: str) -> Path | None:
    """The banked picture for this target, if there is a usable one.

    Returns ``None`` for an entry past :data:`MAX_AGE_DAYS` rather than
    deleting it -- reading is on the hot path of a failing step, and a lookup
    is not the place to mutate the store. :func:`prune` does the deleting.
    """
    if not target_name:
        return None
    png = path_for(scope, target_name)
    if not png.exists():
        return None
    meta = _read_meta(png.with_suffix(".json"))
    saved_at = float(meta.get("saved_at", 0.0)) if meta else 0.0
    if saved_at and (time.time() - saved_at) > MAX_AGE_DAYS * 86400:
        logger.debug("Template for '%s' is stale (%s); ignoring", target_name, png)
        return None
    return png


def save(
    scope: str,
    target_name: str,
    screenshot: bytes,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    method: str,
    confidence: float,
    viewport_width: int | None = None,
) -> Path | None:
    """Bank a crop of ``screenshot`` as the picture of ``target_name``.

    The rectangle is in CSS pixels, as ``bounding_box()`` reports it. The
    screenshot may not be: a device scale factor of 2 makes it twice as wide,
    and cropping CSS coordinates out of a 2x image takes the top-left quarter
    of the element. Pass ``viewport_width`` and the scale is recovered from the
    decoded image.

    Returns the path written, or ``None`` if there was nothing worth writing.
    Never raises: a step that found its element must not fail because the
    bookkeeping afterwards did.
    """
    if not target_name:
        return None
    if width <= 0 or height <= 0:
        return None

    try:
        arr = np.frombuffer(screenshot, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None

        img_h, img_w = img.shape[:2]
        scale = 1.0
        if viewport_width and viewport_width > 0:
            scale = img_w / float(viewport_width)
            # A scale far from a real device ratio means the caller's viewport
            # and this screenshot do not describe the same thing (a full-page
            # capture, a resized window). Cropping on a guess would bank the
            # wrong rectangle, so fall back to 1:1.
            if not 0.5 <= scale <= 4.0:
                scale = 1.0

        x1 = max(0, int(left * scale) - PAD)
        y1 = max(0, int(top * scale) - PAD)
        x2 = min(img_w, int((left + width) * scale) + PAD)
        y2 = min(img_h, int((top + height) * scale) + PAD)

        if x2 - x1 < MIN_SIDE or y2 - y1 < MIN_SIDE:
            return None

        cropped = img[y1:y2, x1:x2]

        scope_dir = templates_root() / (scope or UNSCOPED)
        scope_dir.mkdir(parents=True, exist_ok=True)
        key = key_for(target_name)
        png = scope_dir / f"{key}.png"
        if not cv2.imwrite(str(png), cropped):
            return None

        (scope_dir / f"{key}.json").write_text(
            json.dumps(
                {
                    "target": target_name,
                    "method": method,
                    "confidence": round(float(confidence), 4),
                    "width": int(x2 - x1),
                    "height": int(y2 - y1),
                    "saved_at": time.time(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.debug("Banked template for '%s' → %s", target_name, png)
        # Bound the store here rather than at the start of a run. There is no
        # run-level hook that every entry point passes through -- `aat run`,
        # `aat loop`, `aat watch`, the dashboard and the MCP server each build
        # their own executor -- and a cap that only one of them applies is not
        # a cap. Counting files is cheap, and only at the threshold.
        if len(list(scope_dir.glob("*.png"))) > MAX_PER_SCOPE:
            prune(scope_dir.name)
        return png
    except Exception:
        logger.debug("Banking template for '%s' failed", target_name, exc_info=True)
        return None


def inventory(scope: str | None = None) -> list[TemplateEntry]:
    """Every banked picture, newest first. Empty when the store does not exist."""
    entries = list(_iter_entries(scope))
    entries.sort(key=lambda e: e.saved_at, reverse=True)
    return entries


def prune(
    scope: str | None = None,
    *,
    max_age_days: float | None = None,
    max_per_scope: int | None = None,
) -> int:
    """Delete stale and surplus entries. Returns how many were removed.

    The limits default to :data:`MAX_AGE_DAYS` and :data:`MAX_PER_SCOPE` but
    are resolved on call, not bound at import. ``save`` decides whether to
    prune by reading the module constants, so a default captured at definition
    time would let the two disagree -- the caller triggering a prune that then
    evicts nothing.
    """
    max_age_days = MAX_AGE_DAYS if max_age_days is None else max_age_days
    max_per_scope = MAX_PER_SCOPE if max_per_scope is None else max_per_scope
    removed = 0
    by_scope: dict[str, list[TemplateEntry]] = {}
    for entry in _iter_entries(scope):
        by_scope.setdefault(entry.scope, []).append(entry)

    cutoff = time.time() - max_age_days * 86400
    for entries in by_scope.values():
        entries.sort(key=lambda e: e.saved_at, reverse=True)
        # An entry whose metadata is missing or unreadable has no date, so age
        # cannot condemn it -- but it sorts last, so the count cap evicts it
        # before anything we can actually vouch for.
        doomed = [e for e in entries if e.saved_at and e.saved_at < cutoff]
        survivors = [e for e in entries if e not in doomed]
        if max_per_scope >= 0 and len(survivors) > max_per_scope:
            doomed.extend(survivors[max_per_scope:])
        for entry in doomed:
            removed += _remove(entry)
    return removed


def clear(scope: str | None = None) -> int:
    """Delete every banked picture (optionally for one host only)."""
    return sum(_remove(entry) for entry in _iter_entries(scope))


def _iter_entries(scope: str | None) -> Iterator[TemplateEntry]:
    root = templates_root()
    if not root.is_dir():
        return
    scope_dirs = [root / scope] if scope else sorted(p for p in root.iterdir() if p.is_dir())
    for scope_dir in scope_dirs:
        if not scope_dir.is_dir():
            continue
        for png in sorted(scope_dir.glob("*.png")):
            meta = _read_meta(png.with_suffix(".json"))
            yield TemplateEntry(
                scope=scope_dir.name,
                key=png.stem,
                target=str(meta.get("target", "?")),
                method=str(meta.get("method", "?")),
                confidence=float(meta.get("confidence", 0.0) or 0.0),
                width=int(meta.get("width", 0) or 0),
                height=int(meta.get("height", 0) or 0),
                saved_at=float(meta.get("saved_at", 0.0) or 0.0),
                path=png,
            )


def _read_meta(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _remove(entry: TemplateEntry) -> int:
    try:
        entry.path.unlink(missing_ok=True)
        entry.path.with_suffix(".json").unlink(missing_ok=True)
        # Pre-scoping entries wrote a .txt sidecar. Clean those up too, or
        # `clear` leaves litter behind and reports success.
        entry.path.with_suffix(".txt").unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove template %s", entry.path, exc_info=True)
        return 0
    return 1
