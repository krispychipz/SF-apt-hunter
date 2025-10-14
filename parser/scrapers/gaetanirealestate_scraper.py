"""Scraper for Gaetani Real Estate AppFolio listings."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from parser.models import Unit
from parser.scrapers.jacksongroup_scraper import (
    parse_appfolio_collection as _parse_appfolio_collection,
)

LISTINGS_URL = "https://www.gaetanirealestate.com/vacancies"

# Prefer this AppFolio collection id; fallback to discovery if it fails
COLLECTION_ID_OVERRIDE = "cd92d571"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": LISTINGS_URL,
}

_LOGGER = logging.getLogger(__name__)
parse_appfolio_collection = _parse_appfolio_collection

def _extract_sitealias_from_parameters(html_text: str) -> Optional[str]:
    """Extract SiteAlias value from the window.Parameters script without regex.
    Scans script tags for a window.Parameters object and pulls the quoted value after the SiteAlias key.
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return None
    for sc in soup.find_all("script"):
        try:
            text = sc.string or sc.get_text() or ""
        except Exception:
            continue
        if not text or "window.Parameters" not in text or "SiteAlias" not in text:
            continue
        idx = 0
        while True:
            i = text.find("SiteAlias", idx)
            if i == -1:
                break
            # Find the colon after the key
            j = text.find(":", i)
            if j == -1:
                break
            # Advance to first non-space char
            k = j + 1
            n = len(text)
            while k < n and text[k] in (" ", "\t", "\r", "\n"):
                k += 1
            if k >= n:
                break
            ch = text[k]
            if ch in ("'", '"'):
                quote = ch
                k += 1
                start = k
                # Find closing quote, allowing for simple escaped quotes
                while k < n:
                    if text[k] == "\\":
                        k += 2
                        continue
                    if text[k] == quote:
                        val = text[start:k]
                        return val.strip()
                    k += 1
                # If no closing quote, abort this occurrence
                idx = i + len("SiteAlias")
                continue
            else:
                # Unquoted value; read until comma or newline
                start = k
                while k < n and text[k] not in (",", "\n", "\r", "}"):
                    k += 1
                val = text[start:k].strip()
                if val:
                    return val
                idx = i + len("SiteAlias")
        # continue scanning other scripts
    return None

def _discover_collection_id(session: requests.Session, timeout: int) -> Optional[str]:
    try:
        r = session.get(LISTINGS_URL, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        _LOGGER.debug("Failed vacancies page fetch: %s", e)
        return None
    cid = _extract_sitealias_from_parameters(r.text)
    if cid:
        _LOGGER.debug("Discovered SiteAlias (collection id): %s", cid)
        return cid
    _LOGGER.debug("Collection id not found in vacancies HTML")
    return None

def _build_api_url(collection_id: str) -> str:
    return (
        f"https://www.gaetanirealestate.com/rts/collections/public/{collection_id}"
        "/runtime/collection/appfolio-listings/data"
    )

def _fetch_page(session: requests.Session, api_url: str, page_number: int, page_size: int, timeout: int):
    params = {
        "page": json.dumps({"pageSize": page_size, "pageNumber": page_number}, separators=(",", ":")),
        "language": "ENGLISH",
    }
    response = session.get(api_url, headers=HEADERS, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()

def fetch_units(
    url: str = LISTINGS_URL,
    *,
    timeout: int = 20,
    page_size: int = 100,
    max_pages: int = 10,
) -> List[Unit]:
    """Fetch Gaetani Real Estate listings from dynamic AppFolio collection."""
    session = requests.Session()

    # Try override id first; fallback to discovery if first request fails
    collection_id: Optional[str] = COLLECTION_ID_OVERRIDE
    api_url = _build_api_url(collection_id)

    prefetched_payload = None
    try:
        prefetched_payload = _fetch_page(session, api_url, page_number=0, page_size=page_size, timeout=timeout)
    except Exception as e:
        _LOGGER.debug("Override collection id failed; falling back to discovery: %s", e)
        collection_id = _discover_collection_id(session, timeout)
        if not collection_id:
            _LOGGER.debug("No collection id discovered; aborting.")
            return []
        api_url = _build_api_url(collection_id)
        try:
            prefetched_payload = _fetch_page(session, api_url, page_number=0, page_size=page_size, timeout=timeout)
        except Exception as e2:
            _LOGGER.debug("Fetch failed after discovery: %s", e2)
            return []

    units: List[Unit] = []
    seen: set[tuple[Optional[str], str]] = set()

    for page_number in range(max_pages):
        try:
            if page_number == 0 and prefetched_payload is not None:
                payload = prefetched_payload
            else:
                payload = _fetch_page(session, api_url, page_number=page_number, page_size=page_size, timeout=timeout)
        except requests.HTTPError as e:
            _LOGGER.debug("HTTP error page %d: %s", page_number, e)
            break
        except Exception as e:
            _LOGGER.debug("Fetch error page %d: %s", page_number, e)
            break

        page_units = parse_appfolio_collection(payload, base_url=LISTINGS_URL)
        if not page_units:
            _LOGGER.debug("No units on page %d; stopping pagination.", page_number)
            break

        new_count = 0
        for u in page_units:
            key = (u.address, u.source_url)
            if key in seen:
                continue
            seen.add(key)
            units.append(u)
            new_count += 1

        _LOGGER.debug(
            "Gaetani page %d: %d units (%d new, %d total)",
            page_number, len(page_units), new_count, len(units)
        )

        if new_count == 0:
            break

    return units

# Required by your registry
fetch_units.default_url = LISTINGS_URL  # type: ignore[attr-defined]

__all__ = ["fetch_units", "parse_appfolio_collection", "LISTINGS_URL"]
