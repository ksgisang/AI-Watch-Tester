"""Smart Scan crawler — BFS site crawling with Playwright.

Navigates pages, extracts interactive elements, detects features,
and reports broken links. Sends real-time progress via WebSocket.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from app.config import settings
from app.ws import WSManager

logger = logging.getLogger(__name__)

# Feature detection patterns
FEATURE_DETECTORS: dict[str, dict[str, Any]] = {
    "login_form": {
        "selectors": ["input[type=password]", "form[action*=login]", "form[action*=signin]"],
        "texts": ["로그인", "Login", "Sign in", "Sign In"],
    },
    "search": {
        "selectors": ["input[type=search]", "form[action*=search]", "[role=search]"],
        "texts": ["검색", "Search"],
    },
    "cart": {
        "selectors": ["[class*=cart]", "[class*=basket]", "a[href*=cart]", "a[href*=basket]"],
        "texts": ["장바구니", "Cart", "Basket", "카트"],
    },
    "product_list": {
        "selectors": ["[class*=product-list]", "[class*=product-grid]", "[class*=product-card]"],
        "texts": ["가격", "Price", "₩", "$"],
    },
    "review_form": {
        "selectors": ["[class*=review]", "form[action*=review]", "[class*=rating]"],
        "texts": ["리뷰", "후기", "Review", "평점", "Rating"],
    },
    "comment_form": {
        "selectors": ["[class*=comment]", "form[action*=comment]"],
        "texts": ["댓글", "Comment", "의견"],
    },
    "board_write": {
        "selectors": ["a[href*=write]", "a[href*=create]", "a[href*=new]"],
        "texts": ["글쓰기", "작성", "Write", "New Post", "Create"],
    },
    "file_upload": {
        "selectors": ["input[type=file]"],
        "texts": [],
    },
    "admin_panel": {
        "selectors": ["a[href*=admin]", "a[href*=dashboard]", "a[href*=manage]"],
        "texts": ["관리자", "Admin", "Dashboard", "관리"],
    },
    "newsletter": {
        "selectors": ["form[action*=subscribe]", "form[action*=newsletter]", "[class*=newsletter]"],
        "texts": ["구독", "Subscribe", "Newsletter"],
    },
    "social_login": {
        "selectors": [
            "[class*=google]", "[class*=kakao]", "[class*=naver]",
            "[class*=social]", "[class*=oauth]",
        ],
        "texts": ["Google", "Kakao", "Naver", "카카오", "네이버", "소셜 로그인"],
    },
    "pagination": {
        "selectors": ["[class*=pagination]", "[class*=pager]", "nav[aria-label*=page]"],
        "texts": [],
    },
    "filter_sort": {
        "selectors": ["[class*=filter]", "[class*=sort]", "select[name*=sort]"],
        "texts": ["필터", "정렬", "Filter", "Sort"],
    },
}


def _normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    # Remove fragment, normalize path
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, ""))


def _same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs belong to the same domain."""
    return urlparse(url1).netloc == urlparse(url2).netloc


async def _extract_page_data(page: Any, url: str, *, take_screenshot: bool = True) -> dict:
    """Extract all interactive elements from a page."""
    data: dict[str, Any] = {
        "url": page.url,
        "title": await page.title(),
        "links": [],
        "forms": [],
        "buttons": [],
        "nav_menus": [],
        "inputs": [],
        "screenshot_base64": None,
    }

    # Extract links
    try:
        links = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: (a.textContent || '').trim().substring(0, 200),
                href: a.href,
                visible: a.offsetParent !== null || a.offsetWidth > 0 || a.offsetHeight > 0,
                selector: a.id ? '#' + a.id : (a.className ? 'a.' + a.className.split(' ')[0] : null)
            })).filter(l => l.text || l.href)
        }""")
        data["links"] = links[:200]  # cap
    except Exception:
        pass

    # Extract forms
    try:
        forms = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('form')).map(form => {
                const fields = Array.from(form.querySelectorAll('input, textarea, select')).map(f => ({
                    name: f.name || f.id || '',
                    type: f.type || f.tagName.toLowerCase(),
                    placeholder: f.placeholder || '',
                    required: f.required,
                    selector: f.id ? '#' + f.id : (f.name ? `[name="${f.name}"]` : null)
                })).filter(f => f.type !== 'hidden');
                return {
                    action: form.action || '',
                    method: (form.method || 'get').toUpperCase(),
                    fields: fields,
                    selector: form.id ? '#' + form.id : null
                };
            });
        }""")
        data["forms"] = forms[:20]
    except Exception:
        pass

    # Extract buttons
    try:
        buttons = await page.evaluate("""() => {
            const btns = [
                ...document.querySelectorAll('button'),
                ...document.querySelectorAll('[role=button]'),
                ...document.querySelectorAll('input[type=submit]'),
                ...document.querySelectorAll('input[type=button]')
            ];
            const seen = new Set();
            return btns.filter(b => {
                if (seen.has(b)) return false;
                seen.add(b);
                return true;
            }).map(b => ({
                text: (b.textContent || b.value || '').trim().substring(0, 200),
                type: b.type || 'button',
                selector: b.id ? '#' + b.id : (b.className ? 'button.' + b.className.split(' ')[0] : null)
            })).filter(b => b.text);
        }""")
        data["buttons"] = buttons[:50]
    except Exception:
        pass

    # Extract navigation menus
    try:
        navs = await page.evaluate("""() => {
            const navElements = [
                ...document.querySelectorAll('nav'),
                ...document.querySelectorAll('[role=navigation]')
            ];
            const seen = new Set();
            return navElements.filter(n => {
                if (seen.has(n)) return false;
                seen.add(n);
                return true;
            }).map(nav => {
                const items = Array.from(nav.querySelectorAll('a')).map(a => ({
                    text: (a.textContent || '').trim().substring(0, 100),
                    href: a.href,
                    selector: a.id ? '#' + a.id : null
                })).filter(i => i.text);
                return {
                    items: items,
                    selector: nav.id ? '#' + nav.id : (nav.className ? 'nav.' + nav.className.split(' ')[0] : null)
                };
            }).filter(n => n.items.length > 0);
        }""")
        data["nav_menus"] = navs[:10]
    except Exception:
        pass

    # Extract standalone inputs (outside forms)
    try:
        inputs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input:not(form input), textarea:not(form textarea)')).map(f => ({
                name: f.name || f.id || '',
                type: f.type || 'text',
                placeholder: f.placeholder || '',
                selector: f.id ? '#' + f.id : (f.name ? `[name="${f.name}"]` : null)
            })).filter(f => f.type !== 'hidden');
        }""")
        data["inputs"] = inputs[:30]
    except Exception:
        pass

    # Screenshot
    if take_screenshot:
        try:
            png = await page.screenshot(type="png", full_page=False)
            b64 = base64.b64encode(png).decode("ascii")
            data["screenshot_base64"] = f"data:image/png;base64,{b64}"
        except Exception:
            pass

    return data


async def _detect_features(page: Any, page_text: str) -> list[str]:
    """Detect site features based on selectors and text patterns."""
    detected: list[str] = []

    for feature, patterns in FEATURE_DETECTORS.items():
        found = False

        # Check selectors
        for selector in patterns["selectors"]:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    found = True
                    break
            except Exception:
                continue

        # Check text patterns
        if not found and patterns.get("texts"):
            lower_text = page_text.lower()
            for text in patterns["texts"]:
                if text.lower() in lower_text:
                    found = True
                    break

        if found:
            detected.append(feature)

    return detected


async def _check_link(page: Any, url: str, *, timeout: int = 8000) -> dict | None:
    """Check if a link is broken by navigating. Returns broken link info or None."""
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        if response and response.status >= 400:
            return {"url": url, "status": response.status}
    except Exception as exc:
        err_str = str(exc)
        if "net::ERR_" in err_str or "Timeout" in err_str:
            return {"url": url, "status": 0, "error": err_str[:200]}
    return None


async def crawl_site(
    target_url: str,
    scan_id: int,
    *,
    max_pages: int = 5,
    max_depth: int = 2,
    total_timeout: float = 180.0,  # 3 minutes default
    screenshot_limit: int = 3,
    ws: WSManager | None = None,
) -> dict[str, Any]:
    """BFS crawl a site and extract page data.

    Returns dict with keys: pages, summary, broken_links, detected_features.
    """
    try:
        from aat.core.models import EngineConfig
        from aat.engine.web import WebEngine
    except ImportError as exc:
        return {"error": f"AAT core not installed: {exc}"}

    engine_config = EngineConfig(type="web", headless=settings.playwright_headless)
    engine = WebEngine(engine_config)

    start_time = time.monotonic()
    base_domain = urlparse(target_url).netloc
    visited: set[str] = set()
    pages: list[dict] = []
    all_links: set[str] = set()
    all_features: set[str] = set()
    broken_links: list[dict] = []
    total_forms = 0
    total_buttons = 0
    total_nav_menus = 0

    # BFS queue: (url, depth)
    queue: deque[tuple[str, int]] = deque()
    queue.append((_normalize_url(target_url), 0))

    if ws:
        await ws.broadcast(scan_id, {
            "type": "scan_start",
            "target_url": target_url,
            "max_pages": max_pages,
        })

    try:
        await engine.start()
        page = engine.page

        while queue and len(visited) < max_pages:
            # Timeout check
            elapsed = time.monotonic() - start_time
            if elapsed > total_timeout:
                logger.warning("Scan %d: total timeout (%.0fs)", scan_id, elapsed)
                break

            url, depth = queue.popleft()
            normalized = _normalize_url(url)

            if normalized in visited:
                continue
            if depth > max_depth:
                continue
            if urlparse(normalized).netloc != base_domain:
                continue

            visited.add(normalized)

            # Navigate to page
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=10000
                )
            except Exception as exc:
                logger.debug("Scan %d: failed to navigate %s: %s", scan_id, url, exc)
                broken_links.append({"url": url, "status": 0, "error": str(exc)[:200]})
                continue

            # Check response status
            if response and response.status >= 400:
                broken_links.append({"url": url, "status": response.status})
                continue

            # Wait for page to stabilize
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # proceed even if network isn't fully idle

            # Extract page data
            take_ss = len(pages) < screenshot_limit
            page_data = await _extract_page_data(page, url, take_screenshot=take_ss)
            pages.append(page_data)

            # Collect stats
            total_forms += len(page_data.get("forms", []))
            total_buttons += len(page_data.get("buttons", []))
            total_nav_menus += len(page_data.get("nav_menus", []))

            # Detect features on this page
            try:
                page_text = await page.inner_text("body")
            except Exception:
                page_text = ""
            features = await _detect_features(page, page_text)
            for f in features:
                if f not in all_features:
                    all_features.add(f)
                    if ws:
                        await ws.broadcast(scan_id, {
                            "type": "feature_detected",
                            "feature": f,
                        })

            # Collect links for BFS
            for link in page_data.get("links", []):
                href = link.get("href", "")
                if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                    continue
                abs_url = urljoin(url, href)
                if urlparse(abs_url).netloc == base_domain:
                    norm_link = _normalize_url(abs_url)
                    all_links.add(norm_link)
                    if norm_link not in visited:
                        queue.append((norm_link, depth + 1))

            # WebSocket progress
            if ws:
                await ws.broadcast(scan_id, {
                    "type": "page_scanned",
                    "url": url,
                    "title": page_data.get("title", ""),
                    "pages_scanned": len(pages),
                    "max_pages": max_pages,
                    "links_found": len(all_links),
                    "forms_found": total_forms,
                    "buttons_found": total_buttons,
                    "features": list(all_features),
                })

        # Check for broken external links (sample up to 10)
        external_links = [
            link.get("href", "")
            for p in pages
            for link in p.get("links", [])
            if link.get("href", "") and urlparse(link["href"]).netloc != base_domain
        ]
        for ext_url in external_links[:10]:
            if time.monotonic() - start_time > total_timeout:
                break
            broken = await _check_link(page, ext_url)
            if broken:
                broken_links.append(broken)

    except Exception as exc:
        logger.exception("Scan %d: crawl error", scan_id)
        return {"error": str(exc)}
    finally:
        try:
            await engine.stop()
        except Exception:
            pass

    summary = {
        "total_pages": len(pages),
        "total_links": len(all_links),
        "total_forms": total_forms,
        "total_buttons": total_buttons,
        "total_nav_menus": total_nav_menus,
        "broken_links": len(broken_links),
        "detected_features": sorted(all_features),
    }

    if ws:
        await ws.broadcast(scan_id, {
            "type": "scan_complete",
            "summary": summary,
        })

    return {
        "pages": pages,
        "summary": summary,
        "broken_links": broken_links,
        "detected_features": sorted(all_features),
    }


# ---------------------------------------------------------------------------
# Tier-based scan limits
# ---------------------------------------------------------------------------

def get_scan_limits(tier: str) -> dict[str, int]:
    """Return scan limits based on user tier."""
    limits = {
        "free": {"max_pages": 5, "max_depth": 2, "timeout": 180, "screenshots": 3},
        "pro": {"max_pages": 20, "max_depth": 3, "timeout": 300, "screenshots": 100},
        "team": {"max_pages": 50, "max_depth": 5, "timeout": 600, "screenshots": 100},
    }
    return limits.get(tier, limits["free"])
