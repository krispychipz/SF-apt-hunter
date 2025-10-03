#!/usr/bin/env python3
from __future__ import annotations

import logging
import random
import re
import sys
import time
from dataclasses import dataclass

from typing import Any, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from parser.models import Unit

SEARCH_URL = "https://structureproperties.com/available-rentals/"

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from playwright.sync_api import (  # type: ignore
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback path
    PlaywrightError = PlaywrightTimeoutError = Exception  # type: ignore
    sync_playwright = None  # type: ignore


logging.basicConfig(stream=sys.stderr, level=logging.INFO)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_price_re = re.compile(r"\$?\s*([0-9][\d,]*)(?:\.\d+)?", re.I)
_beds_re  = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bed|beds|br)\b", re.I)
_baths_re = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bath|baths|ba)\b", re.I)

_PLAYWRIGHT_WAIT_SELECTOR = ",".join(
    [
        ".listing-item",
        ".property-item",
        "article.property",
        "article.listing",
        ".rentpress-listing-card",
    ]
)


@dataclass
class _PlaywrightResponse:
    status_code: int
    text: str

    def __post_init__(self) -> None:
        self.content = self.text.encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _PlaywrightSession:
    """Minimal Playwright wrapper with a requests-like interface."""

    def __init__(self, timeout: int = 20) -> None:
        if sync_playwright is None:  # pragma: no cover - safety net
            raise RuntimeError("Playwright is not available")
        self._timeout = max(timeout, 1)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)

        extra_headers = {k: v for k, v in HEADERS.items() if k.lower() != "user-agent"}
        self._context = self._browser.new_context(
            user_agent=HEADERS.get("User-Agent"),
            extra_http_headers=extra_headers,
        )
        self._page = self._context.new_page()
        timeout_ms = self._timeout * 1000
        self._page.set_default_timeout(timeout_ms)
        self._page.set_default_navigation_timeout(timeout_ms)

    def _resolve_timeout_ms(self, timeout: Any) -> int:
        if timeout is None:
            return self._timeout * 1000
        try:
            if isinstance(timeout, (int, float)):
                return int(float(timeout) * 1000)
            for attr in ("read", "read_timeout", "timeout", "total"):
                value = getattr(timeout, attr, None)
                if value is not None:
                    return int(float(value) * 1000)
        except Exception:  # pragma: no cover - defensive
            pass
        return self._timeout * 1000

    def get(self, url: str, *, headers: Optional[dict[str, str]] = None, timeout: Any = None) -> _PlaywrightResponse:
        referer = headers.get("Referer") if headers else None
        timeout_ms = self._resolve_timeout_ms(timeout)
        try:
            response = self._page.goto(
                url,
                referer=referer,
                wait_until="networkidle",
                timeout=timeout_ms,
            )
            # Give dynamic scripts a moment to populate listings.
            try:
                self._page.wait_for_selector(_PLAYWRIGHT_WAIT_SELECTOR, timeout=2000)
            except Exception:  # pragma: no cover - best-effort wait
                pass
            html = self._page.content()
            status = response.status if response else 200
        except PlaywrightTimeoutError as exc:  # pragma: no cover - network flake
            logger.warning("Playwright navigation timeout for %s: %s", url, exc)
            html = self._page.content()
            status = 408
        except PlaywrightError as exc:  # pragma: no cover - unexpected failure
            logger.error("Playwright error navigating to %s: %s", url, exc)
            raise
        return _PlaywrightResponse(status_code=status, text=html)

    def close(self) -> None:
        try:
            self._page.close()
        finally:
            try:
                self._context.close()
            finally:
                try:
                    self._browser.close()
                finally:
                    self._playwright.stop()

def _clean_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = _price_re.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None

def _clean_float(text: Optional[str], kind: str) -> Optional[float]:
    if not text:
        return None
    pat = _beds_re if kind == "beds" else _baths_re
    m = pat.search(text)
    if not m:
        m = re.search(r"\d+(?:\.\d+)?", text)
        if not m:
            return None
    try:
        # if using the fallback pattern above, group(1) may be missing
        grp = m.group(1) if m.lastindex else m.group(0)
        return float(grp)
    except Exception:
        return None

def _candidate_listing_blocks(soup: BeautifulSoup) -> Iterable[Tag]:
    selectors = [
        ".listing.js-listing",
        ".listing-item", ".property-item", "article.property", "article.listing",
        ".rentpress-listing-card", ".property", ".listing", ".rp-listing-card",
        ".grid-item", ".loop-item", ".listingCard"
    ]
    seen: set[int] = set()
    for sel in selectors:
        found = soup.select(sel)
        if found:
            print(found[0].prettify())
        print(f"Selector {sel} found {len(found)} blocks")
        for el in found:
            if isinstance(el, Tag):
                hid = id(el)
                if hid not in seen:
                    seen.add(hid)
                    yield el
    # fallback: parent of anchors that look like detail links
    for a in soup.find_all("a", href=True):
        if re.search(r"/(rent|list|avail|property|apartment|apartments)/", a["href"], re.I):
            parent = a.find_parent()
            if parent:
                hid = id(parent)
                if hid not in seen:
                    seen.add(hid)
                    yield parent
    logger.debug("Structure Properties candidate generator yielded %d blocks", len(seen))

def _text(el: Optional[Tag]) -> str:
    return el.get_text(" ", strip=True) if el else ""

def _extract_address(block: Tag) -> Optional[str]:
    for sel in ["h2.address", "h3.address", ".address", ".property-title", ".listing-title", "h2", "h3"]:
        el = block.select_one(sel)
        txt = _text(el)
        if txt and len(txt) > 5:
            return txt
    a = block.select_one("a[aria-label]")
    if a and a.get("aria-label"):
        return a["aria-label"].strip()
    a = block.select_one("a")
    if a:
        txt = _text(a)
        if txt and len(txt) > 5:
            return txt
    return None

def _extract_rent(block: Tag) -> Optional[int]:
    for sel in [".rent", ".price", ".listing-price", ".property-rent", ".rp-price", ".card-price", ".summary"]:
        el = block.select_one(sel)
        rent = _clean_price(_text(el))
        if rent is not None:
            return rent
    for t in block.stripped_strings:
        rent = _clean_price(t)
        if rent is not None:
            return rent
    return None

def _extract_beds(block: Tag) -> Optional[float]:
    for sel in [".beds", ".bedrooms", ".rp-beds", ".property-beds", ".listing-beds"]:
        el = block.select_one(sel)
        val = _clean_float(_text(el), kind="beds")
        if val is not None:
            return val
    txt = " ".join([t for t in block.stripped_strings])
    return _clean_float(txt, kind="beds")

def _extract_baths(block: Tag) -> Optional[float]:
    for sel in [".baths", ".bathrooms", ".rp-baths", ".property-baths", ".listing-baths"]:
        el = block.select_one(sel)
        val = _clean_float(_text(el), kind="baths")
        if val is not None:
            return val
    txt = " ".join([t for t in block.stripped_strings])
    return _clean_float(txt, kind="baths")

def _extract_neighborhood(block: Tag) -> Optional[str]:
    for sel in [".neighborhood", ".community", ".area", ".location", ".rp-neighborhood"]:
        el = block.select_one(sel)
        if el:
            txt = _text(el)
            if txt and len(txt) > 2:
                return txt
    return None

def _extract_url(block: Tag, base_url: str) -> str:
    a = block.select_one("a[href]")
    href = a.get("href") if a else None
    return urljoin(base_url, href) if href else base_url

def _parse_block(block: Tag, base_url: str) -> Optional[Unit]:
    address = _extract_address(block)
    rent = _extract_rent(block)
    beds = _extract_beds(block)
    baths = _extract_baths(block)
    hood = _extract_neighborhood(block)
    url = _extract_url(block, base_url)
    if not address and not url:
        return None
    return Unit(
        address=address,
        bedrooms=beds,
        bathrooms=baths,
        rent=rent,
        neighborhood=hood,
        source_url=url,
    )

def _find_next_page(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    a = soup.select_one("a[rel='next']")
    if a and a.get("href"):
        return urljoin(current_url, a["href"])
    for sel in [".pagination a.next", ".paginate a.next", ".nav-links a.next", ".pagination a[aria-label='Next']"]:
        a = soup.select_one(sel)
        if a and a.get("href"):
            return urljoin(current_url, a["href"])
    for a in soup.select("a[href]"):
        if a.get_text(strip=True).lower() in {"next", "older posts", "»", "›"}:
            return urljoin(current_url, a["href"])
    current = soup.select_one(".pagination .current, .page-numbers .current")
    if current:
        nxt = current.find_next("a", href=True)
        if nxt:
            return urljoin(current_url, nxt["href"])
    return None

def get_html(url: str, client: Any, referer: Optional[str] = None) -> str:
    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer
    logger.debug("Structure Properties request %s (referer=%s)", url, referer)
    attempts = 3
    timeout = httpx.Timeout(20.0) if httpx else 20.0  # type: ignore[union-attr]
    for attempt in range(1, attempts + 1):
        r = client.get(url, headers=headers, timeout=timeout)
        r.encoding = "utf-8"
        if r.status_code == 200:
            logger.debug(
                "Structure Properties HTTP %s on attempt %d (%d bytes)",
                r.status_code,
                attempt,
                len(r.content),
            )
            return r.text
        if r.status_code in (403, 429, 503) and attempt < attempts:
            sleep_for = 1.0 + attempt - 1 + random.uniform(0, 0.5)
            logger.debug(
                "Structure Properties retrying after %s due to status %s", sleep_for, r.status_code
            )
            time.sleep(sleep_for)
            continue
        r.raise_for_status()
    # If we exit the loop the last response succeeded or raise_for_status() raised.
    return r.text

def _create_http_client() -> tuple[Any, Any]:
    if httpx is not None:
        client = httpx.Client(http2=True, follow_redirects=True, headers=HEADERS)
        return client, client.close
    session = requests.Session()
    session.headers.update(HEADERS)
    return session, session.close


def fetch_units(url: str = SEARCH_URL, *, max_pages: int = 10, timeout: int = 20) -> List[Unit]:
    """
    Fetch and parse Structure Properties available rentals across paginated results.
    Returns a list of Unit objects.
    """
    visited: set[str] = set()
    units: List[Unit] = []
    pages = 0

    logger.debug("Fetching Structure Properties listings from %s (max_pages=%d)", url, max_pages)

    client: Any
    close_client: Any
    if sync_playwright is not None:
        try:
            client = _PlaywrightSession(timeout=timeout)
            close_client = client.close
            logger.debug("Using Playwright rendered session for Structure Properties")
        except Exception as exc:  # pragma: no cover - Playwright init issues
            logger.warning(
                "Playwright unavailable (%s); falling back to HTTP session", exc
            )
            client, close_client = _create_http_client()
    else:
        client, close_client = _create_http_client()

    # 1) warm up
    try:
        landing_html = get_html(SEARCH_URL, client)
        logger.debug("Structure Properties warm-up fetched %d bytes", len(landing_html))

        # 2) start scraping with referer logic
        referer = SEARCH_URL
        current_url = url
        while current_url and pages < max_pages and current_url not in visited:
            visited.add(current_url)
            pages += 1

            html = get_html(current_url, client, referer=referer if pages > 1 else None)
            soup = BeautifulSoup(html, "lxml")
            print("DEBUG: All tag names in soup:", [tag.name for tag in soup.find_all(True)[:20]])
            blocks = list(_candidate_listing_blocks(soup))
            if not blocks:
                blocks = soup.find_all("article")
            logger.debug(
                "Structure Properties page %d (%s) yielded %d block(s)",
                pages,
                current_url,
                len(blocks),
            )

            for b in blocks:
                unit = _parse_block(b, base_url=current_url)
                if unit:
                    if len(units) < 3:
                        logger.debug(
                            "Structure Properties sample listing %d: address=%s rent=%s bedrooms=%s",
                            len(units),
                            unit.address,
                            unit.rent,
                            unit.bedrooms,
                        )
                    units.append(unit)

            next_url = _find_next_page(soup, current_url=current_url)
            referer = current_url
            current_url = next_url
    finally:
        close_client()

    return units

fetch_units.default_url = SEARCH_URL  # type: ignore[attr-defined]

__all__ = ["fetch_units"]
