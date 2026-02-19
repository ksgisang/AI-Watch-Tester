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

# ---------------------------------------------------------------------------
# Feature detection — hybrid: CSS selectors + link/button text matching
# ---------------------------------------------------------------------------
#
# Each detector has:
#   - strong: CSS selectors for definitive UI elements → 0.9 confidence
#   - weak: CSS selectors for less certain matches → 0.3 alone, 0.6 with confirm_texts
#   - link_texts: text patterns to match in link/button text → 0.7 confidence
#   - link_hrefs: href patterns to match in links → 0.7 confidence
#   - threshold: minimum confidence to report (0.0–1.0), default 0.5
#
# Text matching checks actual interactive elements (links, buttons) only,
# avoiding false positives from footer/copyright text.

FEATURE_DETECTORS: dict[str, dict[str, Any]] = {
    "login_form": {
        "strong": ["input[type=password]", "form[action*=login]", "form[action*=signin]"],
        "weak": [],
        "confirm_texts": [],
        "link_texts": ["login", "log in", "sign in", "로그인"],
        "link_hrefs": ["/login", "/signin", "/sign-in", "/log-in"],
        "threshold": 0.5,
    },
    "signup": {
        "strong": ["form[action*=register]", "form[action*=signup]"],
        "weak": [],
        "confirm_texts": [],
        "link_texts": ["sign up", "signup", "register", "join", "회원가입", "가입"],
        "link_hrefs": ["/register", "/signup", "/sign-up", "/join"],
        "threshold": 0.5,
    },
    "search": {
        "strong": ["input[type=search]", "[role=search]", "form[action*=search]"],
        "weak": ["input[placeholder*=search]", "input[placeholder*=검색]"],
        "confirm_texts": [],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "cart": {
        "strong": ["a[href*='/cart']", "a[href*='/basket']", "[data-cart]"],
        "weak": ["[class*=cart-icon]", "[class*=cart-count]", "[class*=basket]"],
        "confirm_texts": ["장바구니", "Cart", "Basket"],
        "link_texts": ["cart", "basket", "장바구니"],
        "link_hrefs": ["/cart", "/basket"],
        "threshold": 0.5,
    },
    "product_list": {
        "strong": ["[class*=product-list]", "[class*=product-grid]", "[class*=product-card]"],
        "weak": ["[class*=item-price]", "[class*=product]"],
        "confirm_texts": [],
        "link_texts": [],
        "link_hrefs": ["/products", "/shop", "/store"],
        "threshold": 0.5,
    },
    "review_form": {
        "strong": ["form[action*=review]", "textarea[name*=review]", "input[name*=rating]"],
        "weak": ["[class*=review-form]", "[class*=rating-input]", "[class*=star-rating]"],
        "confirm_texts": ["리뷰 작성", "Write a review", "후기 작성"],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "comment_form": {
        "strong": ["textarea[name*=comment]", "form[action*=comment]"],
        "weak": ["[class*=comment-form]", "[class*=comment-input]"],
        "confirm_texts": ["댓글 작성", "댓글 등록", "Add comment", "Write comment"],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "board_write": {
        "strong": ["a[href*='/write']", "a[href*='/board/']", "a[href*='/post/new']"],
        "weak": ["a[href*='/create']", "a[href*='/new']"],
        "confirm_texts": ["글쓰기", "새 글", "New Post", "게시판"],
        "link_texts": ["게시판", "board", "forum"],
        "link_hrefs": ["/board", "/forum", "/community", "/write"],
        "threshold": 0.5,
    },
    "blog": {
        "strong": [],
        "weak": [],
        "confirm_texts": [],
        "link_texts": ["blog", "블로그"],
        "link_hrefs": ["/blog", "/posts"],
        "threshold": 0.5,
    },
    "file_upload": {
        "strong": ["input[type=file]"],
        "weak": [],
        "confirm_texts": [],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "admin_panel": {
        "strong": ["a[href*='/admin']"],
        "weak": ["a[href*='/manage']"],
        "confirm_texts": ["관리자 페이지", "Admin Panel", "관리자 로그인"],
        "link_texts": ["admin", "관리자"],
        "link_hrefs": ["/admin"],
        "threshold": 0.5,
    },
    "newsletter": {
        "strong": ["form[action*=subscribe]", "form[action*=newsletter]"],
        "weak": ["[class*=newsletter]", "input[name*=newsletter]"],
        "confirm_texts": ["이메일 구독", "Subscribe", "뉴스레터 구독"],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "social_login": {
        "strong": [
            "button[class*=google-login]", "button[class*=kakao-login]",
            "button[class*=naver-login]", "a[href*=oauth]",
            "[class*=social-login]", "a[href*='accounts.google.com']",
            "a[href*='kauth.kakao.com']", "a[href*='nid.naver.com']",
        ],
        "weak": ["[class*=oauth]", "[class*=social-btn]"],
        "confirm_texts": ["소셜 로그인", "Sign in with", "카카오로 로그인", "네이버로 로그인"],
        "link_texts": ["google", "kakao", "naver", "카카오", "네이버"],
        "link_hrefs": ["/oauth", "/auth/google", "/auth/kakao", "/auth/naver"],
        "threshold": 0.5,
    },
    "multilingual": {
        "strong": [],
        "weak": ["[class*=lang-switch]", "[class*=language]", "select[name*=lang]"],
        "confirm_texts": [],
        "link_texts": ["english", "한국어", "language", "언어"],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "pagination": {
        "strong": ["[class*=pagination]", "nav[aria-label*=page]", "[class*=pager]"],
        "weak": [],
        "confirm_texts": [],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
    "filter_sort": {
        "strong": ["select[name*=sort]", "select[name*=order]", "[class*=filter-panel]"],
        "weak": ["[class*=filter]", "[class*=sort-btn]"],
        "confirm_texts": ["필터", "정렬", "Filter", "Sort by"],
        "link_texts": [],
        "link_hrefs": [],
        "threshold": 0.5,
    },
}


# ---------------------------------------------------------------------------
# Site type detection — classify site based on detected features + URL patterns
# ---------------------------------------------------------------------------

SITE_TYPE_RULES: dict[str, dict[str, Any]] = {
    "ecommerce": {
        "required_features": ["cart", "product_list"],
        "optional_features": ["filter_sort", "review_form", "search", "pagination"],
        "url_patterns": ["/shop", "/store", "/products", "/product", "/cart", "/checkout"],
        "min_score": 4,
    },
    "blog": {
        "required_features": ["blog"],
        "optional_features": ["comment_form", "pagination", "search"],
        "url_patterns": ["/blog", "/posts", "/article", "/tag", "/category"],
        "min_score": 2,
    },
    "community": {
        "required_features": ["board_write"],
        "optional_features": ["comment_form", "pagination", "file_upload", "search"],
        "url_patterns": ["/board", "/forum", "/community", "/thread", "/topic"],
        "min_score": 2,
    },
    "saas": {
        "required_features": ["login_form"],
        "optional_features": ["signup", "search", "admin_panel", "social_login"],
        "url_patterns": ["/dashboard", "/app", "/settings", "/billing", "/api"],
        "min_score": 3,
    },
    "corporate": {
        "required_features": [],
        "optional_features": ["newsletter", "multilingual", "search"],
        "url_patterns": ["/about", "/contact", "/careers", "/team", "/news", "/press"],
        "min_score": 3,
    },
    "portfolio": {
        "required_features": [],
        "optional_features": ["multilingual"],
        "url_patterns": ["/portfolio", "/projects", "/work", "/gallery"],
        "min_score": 2,
    },
}


def _detect_site_type(
    features: list[str],
    all_links: set[str],
    target_url: str,
) -> dict[str, Any]:
    """Classify site type based on detected features and URL patterns.

    Scoring: required feature = +3, optional = +1, URL pattern = +2.
    Returns {"type": str, "confidence": float, "indicators": list[str]}.
    """
    feature_set = set(features)
    all_hrefs_lower = {link.lower() for link in all_links}
    target_lower = target_url.lower()

    best_type = "unknown"
    best_score = 0
    best_max = 1
    best_indicators: list[str] = []

    for site_type, rules in SITE_TYPE_RULES.items():
        score = 0
        indicators: list[str] = []
        max_possible = 0

        # Required features (+3 each)
        for feat in rules["required_features"]:
            max_possible += 3
            if feat in feature_set:
                score += 3
                indicators.append(f"feature:{feat}")

        # Optional features (+1 each)
        for feat in rules["optional_features"]:
            max_possible += 1
            if feat in feature_set:
                score += 1
                indicators.append(f"feature:{feat}")

        # URL patterns (+2 each)
        for pattern in rules["url_patterns"]:
            max_possible += 2
            pattern_lower = pattern.lower()
            if pattern_lower in target_lower or any(
                pattern_lower in href for href in all_hrefs_lower
            ):
                score += 2
                indicators.append(f"url:{pattern}")

        if score >= rules["min_score"] and score > best_score:
            best_type = site_type
            best_score = score
            best_max = max(max_possible, 1)
            best_indicators = indicators

    confidence = round(best_score / best_max, 2) if best_max > 0 else 0.0

    return {
        "type": best_type,
        "confidence": confidence,
        "indicators": best_indicators,
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


async def _detect_features(
    page: Any, page_text: str, page_data: dict | None = None,
) -> list[dict[str, Any]]:
    """Detect site features using CSS selectors + link/button text matching.

    Returns list of {"feature": str, "confidence": float} dicts.
    Only features above their threshold are included.
    """
    detected: list[dict[str, Any]] = []
    lower_text = page_text.lower()

    # Collect interactive element texts and hrefs for text-based matching
    link_texts: list[str] = []
    link_hrefs: list[str] = []
    button_texts: list[str] = []
    if page_data:
        for link in page_data.get("links", []):
            text = (link.get("text") or "").strip().lower()
            href = (link.get("href") or "").lower()
            if text and len(text) < 50:  # skip long paragraph-like texts
                link_texts.append(text)
            if href:
                link_hrefs.append(href)
        for nav in page_data.get("nav_menus", []):
            for item in nav.get("items", []):
                text = (item.get("text") or "").strip().lower()
                href = (item.get("href") or "").lower()
                if text and len(text) < 50:
                    link_texts.append(text)
                if href:
                    link_hrefs.append(href)
        for btn in page_data.get("buttons", []):
            text = (btn.get("text") or "").strip().lower()
            if text and len(text) < 50:
                button_texts.append(text)

    for feature, patterns in FEATURE_DETECTORS.items():
        confidence = 0.0
        threshold = patterns.get("threshold", 0.5)

        # 1. Check strong CSS selectors (high confidence: 0.9)
        for selector in patterns.get("strong", []):
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    confidence = max(confidence, 0.9)
                    break
            except Exception:
                continue

        # 2. Check link/button text patterns (medium-high: 0.7)
        if confidence < 0.9:
            for pat in patterns.get("link_texts", []):
                pat_lower = pat.lower()
                # Match in link text or button text (exact word or contains)
                if any(pat_lower == t or pat_lower in t.split() for t in link_texts):
                    confidence = max(confidence, 0.7)
                    break
                if any(pat_lower == t or pat_lower in t.split() for t in button_texts):
                    confidence = max(confidence, 0.7)
                    break

        # 3. Check link href patterns (medium-high: 0.7)
        if confidence < 0.7:
            for pat in patterns.get("link_hrefs", []):
                pat_lower = pat.lower()
                if any(pat_lower in href for href in link_hrefs):
                    confidence = max(confidence, 0.7)
                    break

        # 4. Check weak CSS selectors (alone: 0.3, with confirm text: 0.6)
        if confidence < 0.6:
            weak_match = False
            for selector in patterns.get("weak", []):
                try:
                    count = await page.locator(selector).count()
                    if count > 0:
                        weak_match = True
                        break
                except Exception:
                    continue

            if weak_match:
                confirm_texts = patterns.get("confirm_texts", [])
                text_confirmed = any(t.lower() in lower_text for t in confirm_texts)
                confidence = max(confidence, 0.6 if text_confirmed else 0.3)

        # Only report features above threshold
        if confidence >= threshold:
            detected.append({"feature": feature, "confidence": round(confidence, 2)})

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
    all_features: dict[str, float] = {}  # feature → confidence
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
            feature_results = await _detect_features(page, page_text, page_data)
            for fr in feature_results:
                fname = fr["feature"]
                fconf = fr["confidence"]
                # Keep highest confidence per feature
                if fname not in all_features or fconf > all_features[fname]:
                    was_new = fname not in all_features
                    all_features[fname] = fconf
                    if was_new and ws:
                        await ws.broadcast(scan_id, {
                            "type": "feature_detected",
                            "feature": fname,
                            "confidence": fconf,
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
                    "features": list(all_features.keys()),
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

    # Build features list with confidence
    features_with_confidence = [
        {"feature": f, "confidence": c}
        for f, c in sorted(all_features.items())
    ]
    feature_names = sorted(all_features.keys())

    # Detect site type
    site_type = _detect_site_type(feature_names, all_links, target_url)

    summary = {
        "total_pages": len(pages),
        "total_links": len(all_links),
        "total_forms": total_forms,
        "total_buttons": total_buttons,
        "total_nav_menus": total_nav_menus,
        "broken_links": len(broken_links),
        "detected_features": feature_names,
        "site_type": site_type,
    }

    # NOTE: scan_complete is NOT broadcast here.
    # It is broadcast from _run_crawl() in scan.py AFTER the DB status is committed,
    # to avoid a race condition where the frontend calls /plan before status is COMPLETED.

    return {
        "pages": pages,
        "summary": summary,
        "broken_links": broken_links,
        "detected_features": feature_names,
        "features_with_confidence": features_with_confidence,
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
