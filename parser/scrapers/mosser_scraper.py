"""Scraper for Mosser Living San Francisco listings."""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from parser.heuristics import clean_neighborhood, money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit

DEFAULT_URL = "https://www.mosserliving.com/san-francisco-apartments/all/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_LOGGER = logging.getLogger(__name__)


def _extract_json_data(tag: Tag) -> Optional[dict[str, Any]]:
    script = tag.find("script", attrs={"type": "application/ld+json"})
    if not script or not script.string:
        return None
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        _LOGGER.debug("Failed to parse JSON-LD block", exc_info=True)
        return None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
        return None
    if isinstance(data, dict):
        return data
    return None


def _parse_property_card(
    card: Tag, *, base_url: str
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    anchor = card.find("a", href=True)
    if not anchor:
        return None
    property_url = urljoin(base_url, anchor["href"])

    data = _extract_json_data(card)
    address: Optional[str] = None
    neighborhood: Optional[str] = None

    subtitle = anchor.select_one(".v-card__subtitle")
    if subtitle:
        text = subtitle.get_text(" ", strip=True)
        cleaned = clean_neighborhood(text)
        neighborhood = cleaned or None

    if data:
        address_info = data.get("address")
        if isinstance(address_info, dict):
            address = address_info.get("streetAddress") or address_info.get("addressLocality")
            if neighborhood is None:
                locality = address_info.get("addressLocality")
                region = address_info.get("addressRegion")
                components = [part for part in [locality, region] if part]
                if components:
                    neighborhood = clean_neighborhood(", ".join(components)) or None

        if not neighborhood:
            name = data.get("name")
            if isinstance(name, str):
                neighborhood = clean_neighborhood(name) or None

    if not address:
        title = anchor.select_one(".rentpress-property-card-title")
        if title:
            address = title.get_text(strip=True) or None

    return property_url, address, neighborhood


def parse_property_list(html: str, *, base_url: str = DEFAULT_URL) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Return property detail URLs with associated metadata."""

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.property-card-wrapper")

    results: List[Tuple[str, Optional[str], Optional[str]]] = []
    for card in cards:
        parsed = _parse_property_card(card, base_url=base_url)
        if parsed is None:
            continue
        results.append(parsed)

    return results


def _extract_floorplan_details(tag: Tag) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    info_el = tag.select_one(".v-card__subtitle")
    info_text = info_el.get_text(" ", strip=True) if info_el else ""

    bedrooms = parse_bedrooms(info_text)
    bathrooms = parse_bathrooms(info_text)

    rent_text = tag.get_text(" ", strip=True)
    rent = money_to_int(rent_text)

    return bedrooms, bathrooms, rent


def parse_property_page(
    html: str,
    *,
    property_url: str,
    address: Optional[str],
    neighborhood: Optional[str],
) -> List[Unit]:
    """Parse an individual property page into :class:`Unit` objects."""

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.rentpress-remove-link-decoration > a[href]")

    units: List[Unit] = []
    for anchor in cards:
        card = anchor.find(class_="rentpress-shortcode-floorplan-card")
        card = card or anchor

        bedrooms, bathrooms, rent = _extract_floorplan_details(card)

        source_url = urljoin(property_url, anchor.get("href", "")) or property_url

        units.append(
            Unit(
                address=address,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                rent=rent,
                neighborhood=neighborhood,
                source_url=source_url,
            )
        )

    return units


def fetch_units(
    url: str = DEFAULT_URL,
    *,
    timeout: int = 20,
    session: Optional[Any] = None,
) -> List[Unit]:
    """Fetch Mosser Living listings and return them as :class:`Unit` objects."""

    client: Any
    close_session = False

    if session is not None:
        client = session
    else:
        client = requests.Session()
        close_session = True

    try:
        if hasattr(client, "headers"):
            try:
                client.headers.update(HEADERS)
            except Exception:  # pragma: no cover - defensive
                pass

        response = client.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()

        properties = parse_property_list(response.text, base_url=url)
        units: List[Unit] = []

        for property_url, address, neighborhood in properties:
            try:
                detail = client.get(property_url, headers=HEADERS, timeout=timeout)
                detail.raise_for_status()
            except requests.RequestException as exc:  # pragma: no cover - network failure
                _LOGGER.warning("Failed to fetch property page %s: %s", property_url, exc)
                continue

            units.extend(
                parse_property_page(
                    detail.text,
                    property_url=property_url,
                    address=address,
                    neighborhood=neighborhood,
                )
            )

        return units
    finally:
        if close_session:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort
                pass


fetch_units.default_url = DEFAULT_URL  # type: ignore[attr-defined]
