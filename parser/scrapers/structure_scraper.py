#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, List, Optional
from urllib.parse import urljoin

import random
import time

import requests
from bs4 import BeautifulSoup, Tag

from parser.models import Unit

SEARCH_URL = "https://structureproperties.com/available-rentals/"

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore


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

def _get_html(url: str, timeout: int = 20) -> str:
    logger.debug("Structure Properties legacy fetch %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    logger.debug("Structure Properties legacy HTTP %s (%d bytes)", resp.status_code, len(resp.content))
    return resp.text

def _candidate_listing_blocks(soup: BeautifulSoup) -> Iterable[Tag]:
    selectors = [
        ".listing-item", ".property-item", "article.property", "article.listing",
        ".rentpress-listing-card", ".property", ".listing", ".rp-listing-card",
        ".grid-item", ".loop-item", ".listingCard"
    ]
    seen: set[int] = set()
    for sel in selectors:
        for el in soup.select(sel):
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

def parse(max_pages: int = 10) -> List[Unit]:
    """
    Scrape Structure Properties available rentals across paginated results.

    Follows common pagination patterns until no 'next' is found or max_pages is reached.
    Returns a list of Unit objects.
    """
    url = SEARCH_URL
    visited: set[str] = set()
    units: List[Unit] = []
    pages = 0

    session = requests.Session()

    while url and pages < max_pages and url not in visited:
        visited.add(url)
        pages += 1

        logger.debug("Structure Properties legacy pagination fetch %s", url)
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        blocks = list(_candidate_listing_blocks(soup))
        if not blocks:
            blocks = soup.find_all("article")
        logger.debug(
            "Structure Properties legacy page %d yielded %d block(s)",
            pages,
            len(blocks),
        )

        for b in blocks:
            unit = _parse_block(b, base_url=url)
            if unit:
                units.append(unit)

        url = _find_next_page(soup, current_url=url)

    return units

def get_html(url: str, client: Any, referer: Optional[str] = None) -> str:
    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer
    logger.debug("Structure Properties request %s (referer=%s)", url, referer)
    for attempt in range(3):
        timeout = httpx.Timeout(20.0) if httpx else 20.0  # type: ignore[union-attr]
        r = client.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            logger.debug(
                "Structure Properties HTTP %s on attempt %d (%d bytes)",
                r.status_code,
                attempt + 1,
                len(r.content),
            )
            return r.text
        if r.status_code in (403, 429, 503):
            time.sleep(1.0 + attempt + random.uniform(0, 0.5))
            continue
        r.raise_for_status()
    # final try or raise
    timeout = httpx.Timeout(20.0) if httpx else 20.0  # type: ignore[union-attr]
    r = client.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    logger.debug(
        "Structure Properties final retry HTTP %s (%d bytes)",
        r.status_code,
        len(r.content),
    )
    return r.text

def fetch_units(url: str = SEARCH_URL, *, max_pages: int = 10, timeout: int = 20) -> List[Unit]:
    """
    Fetch and parse Structure Properties available rentals across paginated results.
    Returns a list of Unit objects.
    """
    visited: set[str] = set()
    units: List[Unit] = []
    pages = 0

    logger.debug("Fetching Structure Properties listings from %s (max_pages=%d)", url, max_pages)

    if httpx is not None:
        client = httpx.Client(http2=True, follow_redirects=True, headers=HEADERS)
        close_client = client.close
    else:  # pragma: no cover - fallback when httpx is unavailable
        client = requests.Session()
        client.headers.update(HEADERS)
        close_client = client.close

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

__all__ = ["fetch_units", "parse"]
