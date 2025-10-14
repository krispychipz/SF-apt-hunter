"""Scraper for Gaetani Real Estate AppFolio listings."""

from __future__ import annotations

import json
import re
import logging
from typing import List, Optional

import requests

from parser.models import Unit
from parser.scrapers.jacksongroup_scraper import (
    parse_appfolio_collection as _parse_appfolio_collection,
)

LISTINGS_URL = "https://www.gaetanirealestate.com/vacancies"

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

_COLLECTION_RE = re.compile(
    r"/rts/collections/public/([a-f0-9]+)/runtime/collection/appfolio-listings/data", re.I
)

def _discover_collection_id(session: requests.Session, timeout: int) -> Optional[str]:
    try:
        r = session.get(LISTINGS_URL, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        _LOGGER.debug("Failed vacancies page fetch: %s", e)
        return None
    m = _COLLECTION_RE.search(r.text)
    if m:
        cid = m.group(1)
        _LOGGER.debug("Discovered collection id: %s", cid)
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
    collection_id = _discover_collection_id(session, timeout)
    if not collection_id:
        _LOGGER.debug("No collection id discovered; aborting.")
        return []

    api_url = _build_api_url(collection_id)
    units: List[Unit] = []
    seen: set[tuple[Optional[str], str]] = set()

    for page_number in range(max_pages):
        try:
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
