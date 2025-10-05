"""Scraper for Jackson Group AppFolio rental listings."""

from __future__ import annotations

import re
import json
import logging
from typing import Any, Iterable, List, Optional
from urllib.parse import urljoin, urlencode

import requests

from parser.models import Unit


LISTINGS_URL = "https://www.jacksongroup.net/find-a-home"
APPFOLIO_API_URL = (
    "https://www.jacksongroup.net/rts/collections/public/40476853/runtime/"
    "collection/appfolio-listings/data?page=%7B%22pageSize%22%3A100%2C%22pageNumber%22%3A0%7D"
    "&language=ENGLISH"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

logger = logging.getLogger(__name__)

API_BASE = "https://www.jacksongroup.net/rts/collections/public/40476853/runtime/collection/appfolio-listings/data"


def _iter_value_entries(obj: Any) -> Iterable[dict[str, Any]]:
    """Yield entries contained inside ``values`` keys recursively."""

    if isinstance(obj, dict):
        values = obj.get("values")
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    yield item
        nested = obj.get("data")
        if isinstance(nested, (dict, list)):
            yield from _iter_value_entries(nested)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_value_entries(item)


def _normalise_listing(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return the underlying listing dictionary for a ``values`` entry."""

    if "data" in entry and isinstance(entry["data"], dict):
        return entry["data"]
    if isinstance(entry.get("listing"), dict):
        return entry["listing"]
    return entry if entry else None


def _clean_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", " "))
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _clean_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", ""))
        if not match:
            return None
        try:
            return int(float(match.group(0)))
        except ValueError:
            return None
    return None


def _compose_address(listing: dict[str, Any]) -> Optional[str]:
    address = listing.get("full_address")
    if isinstance(address, str) and address.strip():
        return address.strip()

    components: List[str] = []
    primary = listing.get("address_address1")
    secondary = listing.get("address_address2")
    city = listing.get("address_city")
    state = listing.get("address_state")
    postal_code = listing.get("address_postal_code")

    for part in (primary, secondary):
        if isinstance(part, str) and part.strip():
            components.append(part.strip())

    locality_parts = [
        part.strip()
        for part in (city or "", state or "", postal_code or "")
        if isinstance(part, str) and part.strip()
    ]
    if locality_parts:
        components.append(", ".join(locality_parts[:2]) if len(locality_parts) > 1 else locality_parts[0])
        if len(locality_parts) > 2:
            components[-1] = ", ".join(locality_parts)

    if not components:
        return None
    if len(components) == 1:
        return components[0]
    return ", ".join(components)


def _detail_url(listing: dict[str, Any]) -> Optional[str]:
    listable_uid = listing.get("listable_uid") or listing.get("page_item_url")
    if not listable_uid:
        return None

    database_url = listing.get("database_url")
    if isinstance(database_url, str) and database_url.strip():
        base = database_url.strip()
    else:
        base = "https://jacksongroup.appfolio.com/"

    detail_path = f"listings/detail/{listable_uid}"
    return urljoin(base, detail_path)


def _resolve_source_url(listing: dict[str, Any], *, fallback: str) -> str:
    for candidate in (
        _detail_url(listing),
        listing.get("rental_application_url"),
        listing.get("schedule_showing_url"),
        listing.get("portfolio_url"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return fallback


def _listing_to_unit(listing: dict[str, Any], *, fallback_url: str) -> Optional[Unit]:
    address = _compose_address(listing)
    bedrooms = _clean_float(listing.get("bedrooms"))
    bathrooms = _clean_float(listing.get("bathrooms"))
    rent = _clean_int(listing.get("market_rent") or listing.get("rent"))

    fallback = fallback_url if address else ""
    source_url = _resolve_source_url(listing, fallback=fallback)

    if not source_url:
        return None

    if not address and not any(value is not None for value in (bedrooms, bathrooms, rent)):
        return None

    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=None,
        source_url=source_url,
    )


def parse_appfolio_collection(data: Any, *, base_url: str = LISTINGS_URL) -> List[Unit]:
    """Parse the Jackson Group AppFolio JSON payload into :class:`Unit` objects."""

    units: List[Unit] = []
    seen: set[tuple[Optional[str], str]] = set()

    for entry in _iter_value_entries(data):
        listing = _normalise_listing(entry)
        if not isinstance(listing, dict):
            continue
        unit = _listing_to_unit(listing, fallback_url=base_url)
        if not unit:
            continue
        key = (unit.address, unit.source_url)
        if key in seen:
            continue
        seen.add(key)
        units.append(unit)

    if units:
        return units

    if isinstance(data, dict):
        listing = _normalise_listing(data)
        if isinstance(listing, dict):
            unit = _listing_to_unit(listing, fallback_url=base_url)
            if unit:
                return [unit]

    return units


def _build_api_params(page_number: int, page_size: int = 100) -> dict[str, str]:
    # page param must be JSON then URL-encoded by requests via params
    page_obj = {"pageSize": page_size, "pageNumber": page_number}
    return {
        "page": json.dumps(page_obj, separators=(",", ":")),
        "language": "ENGLISH",
    }


def fetch_units(
    url: str = LISTINGS_URL,
    *,
    timeout: int = 20,
    max_pages: int = 10,
    page_size: int = 100,
) -> List[Unit]:
    """Fetch Jackson Group listings from the AppFolio JSON endpoint (paginated)."""
    all_units: List[Unit] = []
    seen: set[tuple[Optional[str], str]] = set()

    for page in range(max_pages):
        params = _build_api_params(page, page_size)
        try:
            resp = requests.get(API_BASE, headers=HEADERS, params=params, timeout=timeout)
        except Exception as e:
            logger.debug("Page %d request failed: %s", page, e)
            break

        ctype = resp.headers.get("Content-Type", "")
        if "json" not in ctype.lower():
            logger.debug("Non-JSON response (page %d, content-type=%s); stopping.", page, ctype)
            break

        try:
            payload = resp.json()
        except ValueError:
            logger.debug("JSON decode failed page %d; stopping.", page)
            break

        page_units = parse_appfolio_collection(payload, base_url=LISTINGS_URL)
        if not page_units:
            logger.debug("No units on page %d; stopping pagination.", page)
            break

        new_count = 0
        for u in page_units:
            key = (u.address, u.source_url)
            if key in seen:
                continue
            seen.add(key)
            all_units.append(u)
            new_count += 1

        logger.debug(
            "JacksonGroup page %d: %d units (%d new, %d total)",
            page, len(page_units), new_count, len(all_units)
        )

        if new_count == 0:
            logger.debug("No new unique units page %d; stopping.", page)
            break

    return all_units


fetch_units.default_url = LISTINGS_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_appfolio_collection", "APPFOLIO_API_URL", "LISTINGS_URL"]

