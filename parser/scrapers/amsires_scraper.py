"""Scraper for AMS IRES rental listings via the AppFolio JSON endpoint."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests

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


def _join_nonempty(parts: Iterable[Any]) -> Optional[str]:
    values: List[str] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            values.append(text)
    if not values:
        return None
    return ", ".join(values)


def _compose_address(data: Dict[str, Any]) -> Optional[str]:
    return _first_nonempty(
        data.get("full_address"),
        _join_nonempty(
            (
                data.get("address_address1"),
                data.get("address_address2"),
                data.get("address_city"),
                data.get("address_state"),
                data.get("address_postal_code"),
            )
        ),
        _join_nonempty(
            (
                data.get("portfolio_address1"),
                data.get("portfolio_address2"),
                data.get("portfolio_city"),
                data.get("portfolio_state"),
                data.get("portfolio_postal_code"),
            )
        ),
    )


def _extract_unit_from_values(
    entry: Dict[str, Any], *, base_url: str
) -> Optional[Unit]:
    data = entry.get("data") if isinstance(entry, dict) else None
    if not isinstance(data, dict):
        return None

    address = _compose_address(data)
    bedrooms = _to_float(data.get("bedrooms"))
    bathrooms = _to_float(data.get("bathrooms"))
    rent = _to_int(
        data.get("market_rent")
        or data.get("rent")
        or data.get("min_rent")
        or data.get("max_rent")
    )
    neighborhood = _first_nonempty(
        data.get("address_city"),
        data.get("portfolio_city"),
    )

    source_url = _first_nonempty(
        data.get("rental_application_url"),
        data.get("schedule_showing_url"),
    )

    listable_uid = data.get("listable_uid") or entry.get("page_item_url")
    database_url = data.get("database_url")

    if not source_url and listable_uid:
        listing_path = f"listings/detail/{listable_uid}"
        if isinstance(database_url, str) and database_url.strip():
            source_url = urljoin(database_url, listing_path)
        else:
            source_url = urljoin(base_url, listing_path)

    if source_url and source_url.startswith("/"):
        source_url = urljoin(base_url, source_url)

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

    for entry in _extract_values_entries(data):
        unit = _extract_unit_from_values(entry, base_url=base_url)
        if not unit:
            continue
        key = (unit.address, unit.source_url)
        if key in seen:
            continue
        seen.add(key)
        units.append(unit)

    if units:
        return units

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


def _extract_values_entries(data: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(data, dict):
        values = data.get("values")
        if isinstance(values, list):
            for entry in values:
                if isinstance(entry, dict):
                    yield entry
        nested = data.get("data")
        if isinstance(nested, (dict, list)):
            yield from _extract_values_entries(nested)
    elif isinstance(data, list):
        for item in data:
            yield from _extract_values_entries(item)




def _extract_items(data: Any) -> Optional[List[Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "values"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        nested = data.get("data")
        if nested is not None:
            return _extract_items(nested)
    return None


def fetch_units(
    url: str = SEARCH_URL,
    *,
    timeout: int = 20,
    page_size: int = 100,
    max_pages: int = 10,
    language: str = "ENGLISH",
) -> List[Unit]:
    """Fetch AMS IRES listings directly from the JSON API."""

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        session.get(SEARCH_URL, timeout=timeout)
    except requests.RequestException:
        logger.debug("Warm-up request to %s failed", SEARCH_URL, exc_info=True)

    api_url = url if "appfolio-listings/data" in url else API_URL
    base_url = SEARCH_URL

    units: List[Unit] = []
    seen: set[Tuple[Optional[str], str]] = set()

    for page_number in range(max_pages):
        page_payload = json.dumps(
            {"pageSize": page_size, "pageNumber": page_number},
            separators=(",", ":"),
        )
        params = {"page": page_payload, "language": language}
        response = session.get(api_url, params=params, timeout=timeout)
        if response.status_code == 404:
            break
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:  # pragma: no cover - defensive guard
            logger.warning("AMS IRES API returned non-JSON response")
            break

        items = _extract_items(payload)
        page_units = parse_appfolio_json(payload, base_url=base_url)
        if not page_units and not items:
            break

        for unit in page_units:
            key = (unit.address, unit.source_url)
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)

        if items is not None and len(items) < page_size:
            break

    return units


fetch_units.default_url = SEARCH_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_appfolio_json"]
