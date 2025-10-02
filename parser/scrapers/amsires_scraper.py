"""Scraper for AMS IRES rental listings."""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, cast
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from parser.models import Unit


logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.amsires.com/unfurnished-rentals-search"

HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

JSON_HEADERS = dict(HTML_HEADERS)
JSON_HEADERS["Accept"] = "application/json, text/plain;q=0.9,*/*;q=0.8"

def _iter_pairs(obj: Any, *, _seen: Optional[set[int]] = None) -> Iterable[Tuple[str, Any]]:
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return
    _seen.add(obj_id)
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key.lower(), value
            yield from _iter_pairs(value, _seen=_seen)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_pairs(item, _seen=_seen)


def _normalise_value(value: Any, *, _seen: Optional[set[int]] = None) -> Optional[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    if _seen is None:
        _seen = set()
    value_id = id(value)
    if value_id in _seen:
        return None
    _seen.add(value_id)
    if isinstance(value, dict):
        for key in ("value", "displayvalue", "display", "rawvalue", "text", "label", "values"):
            if key in value:
                candidate = _normalise_value(value[key], _seen=_seen)
                if candidate:
                    return candidate
        for sub in value.values():
            candidate = _normalise_value(sub, _seen=_seen)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for item in value:
            candidate = _normalise_value(item, _seen=_seen)
            if candidate:
                return candidate
    return None


def _extract_field(data: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
    lookup = {key.lower() for key in keys}
    for key, value in _iter_pairs(data):
        if key in lookup:
            normalised = _normalise_value(value)
            if normalised:
                return normalised
    return None


def _normalise_url(candidate: str, *, base_url: str) -> Optional[str]:
    if not candidate:
        return None
    candidate = candidate.strip()
    if not candidate or candidate.lower().startswith("javascript:"):
        return None
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    url = urljoin(base_url, candidate)
    lowered = url.lower()
    if any(lowered.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")):
        return None
    return url


def _extract_url(data: Dict[str, Any], *, base_url: str) -> Optional[str]:
    preferred_keys = (
        "url",
        "href",
        "link",
        "detailurl",
        "permalink",
        "website",
        "listingurl",
        "appfoliolistingurl",
        "toururl",
    )
    for key in preferred_keys:
        value = _extract_field(data, (key,))
        if value:
            url = _normalise_url(value, base_url=base_url)
            if url:
                return url

    for _, value in _iter_pairs(data):
        candidate = _normalise_value(value)
        if not candidate or not isinstance(candidate, str):
            continue
        url = _normalise_url(candidate, base_url=base_url)
        if not url:
            continue
        if "appfolio" in url or "amsires" in url:
            return url
        if not any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")):
            return url
    return None


def _parse_json_listing(item: Dict[str, Any], *, base_url: str) -> Optional[Unit]:
    address = _extract_field(item, ("address", "streetaddress", "address1", "addressline1", "propertyaddress", "location"))
    rent_value = None
    for key in ("rent", "price", "monthlyrent", "minrent", "maxrent", "baserent", "amount"):
        rent_value = _extract_field(item, (key,))
        rent = _clean_price(rent_value)
        if rent is not None:
            break
    else:
        rent = None

    bedrooms_value = _extract_field(item, ("bedrooms", "beds", "bed"))
    bedrooms = _clean_float(bedrooms_value) if bedrooms_value else None

    bathrooms_value = _extract_field(item, ("bathrooms", "baths", "bath"))
    bathrooms = _clean_float(bathrooms_value) if bathrooms_value else None

    neighborhood = _extract_field(item, ("neighborhood", "area", "district", "community", "region"))

    source_url = _extract_url(item, base_url=base_url)

    if not address and not source_url:
        return None

    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=neighborhood,
        source_url=source_url or base_url,
    )


def parse_appfolio_json(data: Any, *, base_url: str) -> List[Unit]:
    candidates: List[List[Dict[str, Any]]] = []

    def _collect(obj: Any) -> None:
        if isinstance(obj, list):
            if obj and all(isinstance(entry, dict) for entry in obj):
                candidates.append(cast(List[Dict[str, Any]], obj))
            for item in obj:
                _collect(item)
        elif isinstance(obj, dict):
            for value in obj.values():
                _collect(value)

    _collect(data)

    units: List[Unit] = []
    seen: set[Tuple[Optional[str], Optional[str]]] = set()
    for candidate in candidates:
        for entry in candidate:
            unit = _parse_json_listing(entry, base_url=base_url)
            if not unit:
                continue
            key = (unit.source_url, unit.address)
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)
    return units


def _find_api_url(html_text: str, *, base_url: str) -> Optional[str]:
    # First look for a fully qualified URL including query parameters.
    url_match = re.search(r"((?:https?:)?//[^'\"\s]+appfolio-listings/data)", html_text, re.IGNORECASE)
    candidate: Optional[str] = None
    if url_match:
        candidate = html.unescape(url_match.group(1))
    else:
        path_match = re.search(
            r"(/rts/collections/public/[0-9a-z-]+/runtime/collection/appfolio-listings/data)",
            html_text,
            re.IGNORECASE,
        )
        if path_match:
            candidate = urljoin(base_url, html.unescape(path_match.group(1)))

    if not candidate:
        return None

    candidate = candidate.replace("\\/", "/")
    parsed = urlsplit(candidate)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query: Dict[str, str] = {key: value for key, value in query_items}

    if "page" not in query:
        query["page"] = json.dumps({"pageSize": 100, "pageNumber": 0}, separators=(",", ":"))
    if "language" not in query:
        query["language"] = "ENGLISH"

    new_query = urlencode(query, doseq=True)
    rebuilt = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))
    if not rebuilt.startswith("http"):
        return urljoin(base_url, rebuilt)
    return rebuilt
    return None


def _next_page_url(url: str, *, page_number: int) -> Optional[str]:
    parsed = urlsplit(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_dict = dict(query_items)
    if "page" not in query_dict:
        return None
    try:
        page_payload = json.loads(query_dict["page"])
    except json.JSONDecodeError:
        return None
    if not isinstance(page_payload, dict):
        return None
    page_payload["pageNumber"] = page_number
    if "pageSize" not in page_payload:
        page_payload["pageSize"] = 100
    query_dict["page"] = json.dumps(page_payload, separators=(",", ":"))
    new_query = urlencode(query_dict, doseq=True)
    new_parts = (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        new_query,
        parsed.fragment,
    )
    return urlunsplit(new_parts)


def _extract_pagination(data: Any) -> Optional[Tuple[int, int]]:
    for obj in _iter_dicts(data):
        page_number: Optional[Any] = None
        for key in ("pageNumber", "pagenumber", "currentPage", "currentpage"):
            if key in obj and obj[key] is not None:
                page_number = obj[key]
                break

        total_pages: Optional[Any] = None
        for key in ("totalPages", "totalpages"):
            if key in obj and obj[key] is not None:
                total_pages = obj[key]
                break

        if page_number is None or total_pages is None:
            continue
        try:
            current = int(float(page_number))
            total = int(float(total_pages))
        except (TypeError, ValueError):
            continue
        return current, total
    return None


def _iter_dicts(obj: Any, *, _seen: Optional[set[int]] = None) -> Iterable[Dict[str, Any]]:
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return
    _seen.add(obj_id)
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value, _seen=_seen)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item, _seen=_seen)


def _clean_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"[\$\s]*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    num = m.group(1).replace(",", "")
    try:
        return int(float(num))
    except ValueError:
        return None

def _clean_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None

def _extract_neighborhood(container: BeautifulSoup) -> Optional[str]:
    """Try a few common patterns for neighborhood labels on AppFolio/AMS IRES templates."""
    # Look for any element with class containing 'neigh'
    el = container.select_one(".neighborhood, [class*='neigh']")
    if el and el.get_text(strip=True):
        return el.get_text(strip=True)
    # Sometimes shown as a 'tag' or in an 'amenities' block
    for sel in [".tags .tag", ".amenities .neighborhood", ".location .neighborhood"]:
        el = container.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return None

def _parse_listing(div: BeautifulSoup, base_url: str) -> Optional[Unit]:
    # Source URL
    a = div.select_one("a.slider-link")
    href = a.get("href") if a else None
    source_url = urljoin(base_url, href) if href else base_url

    # Address
    addr_el = div.select_one("h2.address, .address")
    address = addr_el.get_text(strip=True) if addr_el else None

    # Rent
    rent_el = div.select_one("h3.rent")
    rent = None
    if rent_el:
        # The element sometimes nests a "RENT" label div; get all text
        rent = _clean_price(rent_el.get_text(" ", strip=True))

    # Bedrooms and bathrooms
    beds_el = div.select_one(".feature.beds")
    baths_el = div.select_one(".feature.baths")
    bedrooms = _clean_float(beds_el.get_text(strip=True)) if beds_el else None
    bathrooms = _clean_float(baths_el.get_text(strip=True)) if baths_el else None

    neighborhood = _extract_neighborhood(div)

    # If we have at least a URL or an address, keep it
    if not address and not source_url:
        return None

    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=neighborhood,
        source_url=source_url,
    )


def parse_listings(html: str, *, base_url: str) -> List[Unit]:
    """Parse raw *html* from the AMS IRES listings page."""

    soup = BeautifulSoup(html, "lxml")

    containers = soup.select("div.listing-item")
    logger.debug("AMS IRES parser located %d potential listing containers", len(containers))

    units: List[Unit] = []
    for idx, div in enumerate(containers):
        unit = _parse_listing(div, base_url=base_url)
        if unit:
            if idx < 3:
                logger.debug(
                    "AMS IRES sample listing %d: address=%s rent=%s bedrooms=%s",
                    idx,
                    unit.address,
                    unit.rent,
                    unit.bedrooms,
                )
            units.append(unit)
    return units


def _fetch_api_units(api_url: str, *, base_url: str, timeout: int) -> List[Unit]:
    logger.debug("Fetching AMS IRES API data from %s", api_url)
    units: List[Unit] = []
    seen: set[Tuple[Optional[str], Optional[str]]] = set()
    next_url = api_url
    visited: set[str] = set()

    while next_url and next_url not in visited:
        visited.add(next_url)
        response = requests.get(next_url, headers=JSON_HEADERS, timeout=timeout)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            logger.warning("AMS IRES API returned non-JSON payload: %s", exc)
            break

        page_units = parse_appfolio_json(payload, base_url=base_url)
        for unit in page_units:
            key = (unit.source_url, unit.address)
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)

        pagination = _extract_pagination(payload)
        if not pagination:
            break
        current_page, total_pages = pagination
        if current_page + 1 >= total_pages:
            break
        candidate = _next_page_url(next_url, page_number=current_page + 1)
        if not candidate:
            break
        next_url = candidate

    return units


def fetch_units(url: str = SEARCH_URL, *, timeout: int = 20) -> List[Unit]:
    """Fetch and parse AMS IRES listings from *url*."""

    logger.debug("Fetching AMS IRES listings from %s", url)

    if "appfolio-listings/data" in url:
        return _fetch_api_units(url, base_url=url, timeout=timeout)

    response = requests.get(url, headers=HTML_HEADERS, timeout=timeout)
    response.raise_for_status()
    logger.debug("AMS IRES HTTP %s (%d bytes)", response.status_code, len(response.content))

    html_text = response.text
    units = parse_listings(html_text, base_url=url)
    if units:
        return units

    api_url = _find_api_url(html_text, base_url=url)
    if not api_url:
        logger.debug("AMS IRES HTML parser produced no units and no API endpoint was discovered")
        return units

    logger.debug("AMS IRES falling back to AppFolio API endpoint %s", api_url)
    api_units = _fetch_api_units(api_url, base_url=url, timeout=timeout)
    return api_units or units


fetch_units.default_url = SEARCH_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_listings", "parse_appfolio_json"]
