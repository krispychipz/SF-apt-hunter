"""Scraper for AMS IRES rental listings via the AppFolio JSON endpoint."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit


logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.amsires.com/unfurnished-rentals-search"
API_URL = (
    "https://www.amsires.com/rts/collections/public/038b4f79/runtime/collection/"
    "appfolio-listings/data"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.amsires.com",
    "Referer": SEARCH_URL,
    "Connection": "keep-alive",
}

_number_re = re.compile(r"(\d+(?:\.\d+)?)")

# Heuristic helpers for address and price parsing
_address_has_digit_re = re.compile(r"\d")


def _looks_like_street_address(text: Optional[str]) -> bool:
    return bool(text and _address_has_digit_re.search(text))


def _clean_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return int(float(m.group(0).replace(",", "")))
    except ValueError:
        return None


def _unwrap(value: Any, *, _seen: Optional[set[int]] = None) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return value
    if _seen is None:
        _seen = set()
    obj_id = id(value)
    if obj_id in _seen:
        return None
    _seen.add(obj_id)
    if isinstance(value, dict):
        for key in ("value", "rawValue", "displayValue", "display", "text", "label"):
            if key in value:
                unwrapped = _unwrap(value[key], _seen=_seen)
                if unwrapped is not None:
                    return unwrapped
        if "values" in value:
            unwrapped = _unwrap(value["values"], _seen=_seen)
            if unwrapped is not None:
                return unwrapped
        for sub in value.values():
            unwrapped = _unwrap(sub, _seen=_seen)
            if unwrapped is not None:
                return unwrapped
    elif isinstance(value, list):
        for item in value:
            unwrapped = _unwrap(item, _seen=_seen)
            if unwrapped is not None:
                return unwrapped
    return None


def _candidate_dicts(item: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(item, dict):
        yield item
        attributes = item.get("attributes")
        if isinstance(attributes, dict):
            yield attributes
        property_info = item.get("property")
        if isinstance(property_info, dict):
            yield property_info
        links = item.get("links")
        if isinstance(links, dict):
            yield links


def _raw_value(item: Any, key: str) -> Any:
    lowered = key.lower()
    for container in _candidate_dicts(item):
        for container_key, value in container.items():
            if isinstance(container_key, str) and container_key.lower() == lowered:
                return value
    return None


def _value(item: Any, key: str) -> Optional[Any]:
    return _unwrap(_raw_value(item, key))


def _first_nonempty(*vals: Any) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, (int, float)):
            candidate = str(v)
        else:
            candidate = str(v)
        stripped = candidate.strip()
        if stripped:
            return stripped
    return None


def _to_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val)
    digits = "".join(ch for ch in s if ch.isdigit() or ch == ",")
    if not digits:
        return None
    try:
        return int(digits.replace(",", ""))
    except ValueError:
        return None


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val)
    num = ""
    decimal_seen = False
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch == "." and not decimal_seen:
            num += ch
            decimal_seen = True
    if not num:
        return None
    try:
        return float(num)
    except ValueError:
        return None


def _extract_unit(item: Dict[str, Any], *, base_url: str) -> Optional[Unit]:
    address = _first_nonempty(
        _value(item, "address"),
        _value(item, "formattedAddress"),
        _value(item, "propertyAddress"),
        _value(item, "location"),
        _value(item, "title"),
        _value(item, "name"),
    )

    bedrooms = _to_float(_value(item, "bedrooms") or _value(item, "beds"))
    bathrooms = _to_float(_value(item, "bathrooms") or _value(item, "baths"))

    rent: Optional[int] = None
    for key in ("rent", "price", "monthlyRent", "minRent", "maxRent"):
        rent = _to_int(_value(item, key))
        if rent is not None:
            break
    if rent is None:
        pricing = _raw_value(item, "pricing")
        if isinstance(pricing, dict):
            rent = _to_int(
                _value(pricing, "rent")
                or _value(pricing, "amount")
                or _value(pricing, "min")
            )

    neighborhood = _first_nonempty(
        _value(item, "neighborhood"),
        _value(item, "area"),
        _value(item, "community"),
        _value(item, "region"),
        _value(item, "district"),
    )
    if not neighborhood:
        property_info = _raw_value(item, "property")
        if isinstance(property_info, dict):
            neighborhood = _first_nonempty(
                _value(property_info, "neighborhood"),
                _value(property_info, "area"),
            )

    source_url = _first_nonempty(
        _value(item, "detailUrl"),
        _value(item, "url"),
        _value(item, "listingUrl"),
        _value(item, "appfolioListingUrl"),
        _value(item, "website"),
        _value(item, "self"),
    )
    if source_url and source_url.startswith("/"):
        source_url = urljoin(base_url, source_url)

    # Require either: a detail URL, or any numeric attribute, or an address-like string with digits
    is_detail_url = bool(
        source_url
        and ("/listings/detail/" in source_url or "appfolio.com/listings/detail" in source_url)
    )
    has_numeric_attr = any(v is not None for v in (bedrooms, bathrooms, rent))
    if not is_detail_url and not has_numeric_attr and not _looks_like_street_address(address):
        return None

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


def _iter_listing_dicts(obj: Any, *, _seen: Optional[set[int]] = None) -> Iterable[Dict[str, Any]]:
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return
    _seen.add(obj_id)
    if isinstance(obj, dict):
        if any(
            key in obj
            for key in (
                "attributes",
                "address",
                "formattedAddress",
                "propertyAddress",
                "title",
                "name",
                "location",
            )
        ):
            yield obj
        for value in obj.values():
            yield from _iter_listing_dicts(value, _seen=_seen)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_listing_dicts(item, _seen=_seen)


def parse_appfolio_json(data: Any, *, base_url: str) -> List[Unit]:
    units: List[Unit] = []
    seen: set[Tuple[Optional[str], str]] = set()
    for candidate in _iter_listing_dicts(data):
        unit = _extract_unit(candidate, base_url=base_url)
        if not unit:
            continue
        key = (unit.address, unit.source_url)
        if key in seen:
            continue
        seen.add(key)
        units.append(unit)
    return units


def _extract_items(data: Any) -> Optional[List[Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        nested = data.get("data")
        if nested is not None:
            return _extract_items(nested)
    return None


def _html_unit_from_card(card: BeautifulSoup, base_url: str) -> Optional[Unit]:
    # Source URL from the photo link
    a = card.select_one(".photo a.slider-link[href]")
    href = a.get("href") if a else None
    source_url = urljoin(base_url, href) if href else base_url

    # Address: prefer explicit address node, then aria-label, then slug fallback
    addr = None
    addr_el = card.select_one(".photo h2.address")
    if addr_el:
        addr = addr_el.get_text(strip=True)
    if not addr and a and a.get("aria-label"):
        addr = a["aria-label"].strip()
    if not addr and href:
        m = re.search(r"/listings/detail/([^/?#]+)", href)
        if m:
            addr = m.group(1).replace("-", " ").strip().title()

    # Rent: <h3 class="rent"><div class="smaller">RENT</div>$7,200</h3>
    rent_el = card.select_one("h3.rent")
    rent = _clean_price(rent_el.get_text(" ", strip=True) if rent_el else None)

    # Beds: <div class="amenities"><div class="feature beds">3 beds</div>...</div>
    beds = None
    beds_el = card.select_one(".amenities .feature.beds")
    if beds_el:
        m = _number_re.search(beds_el.get_text(" ", strip=True))
        if m:
            try:
                beds = float(m.group(1))
            except ValueError:
                beds = None

    # Baths: <div class="feature baths">1.5 baths</div>
    baths = None
    baths_el = card.select_one(".amenities .feature.baths")
    if baths_el:
        m = _number_re.search(baths_el.get_text(" ", strip=True))
        if m:
            try:
                baths = float(m.group(1))
            except ValueError:
                baths = None

    if not addr and not source_url:
        return None

    return Unit(
        address=addr,
        bedrooms=beds,
        bathrooms=baths,
        rent=rent,
        neighborhood=None,
        source_url=source_url,
    )


def parse_listings(html: str, *, base_url: str) -> List[Unit]:
    """Parse AMS IRES HTML search results into Unit objects from div.listing-item cards only."""
    soup = BeautifulSoup(html, "lxml")

    # Only consider explicit listing-item cards
    cards: List[BeautifulSoup] = list(soup.select("div.listing-item"))

    units: List[Unit] = []
    for card in cards:
        u = _html_unit_from_card(card, base_url)
        if u:
            units.append(u)
    return units


def fetch_units(
    url: str = SEARCH_URL,
    *,
    timeout: int = 20,
    # ...existing parameters retained for compatibility but unused in HTML mode...
    page_size: int = 100,
    max_pages: int = 10,
    language: str = "ENGLISH",
) -> List[Unit]:
    """Fetch AMS IRES listings by requesting the HTML page and parsing div.listing-item cards."""

    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(url or SEARCH_URL, timeout=timeout)
    response.raise_for_status()
    html_text = response.text

    units = parse_listings(html_text, base_url=url or SEARCH_URL)
    return units


fetch_units.default_url = SEARCH_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_appfolio_json", "parse_listings"]
