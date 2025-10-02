"""Scraper for Anchor Realty rental listings."""

from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple, Union
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit


logger = logging.getLogger(__name__)

LISTING_URLS = (
    "https://anchorrlty.appfolio.com/listings?filters%5Border_by%5D=date_posted",
    "https://anchordc.appfolio.com/listings?filters%5Border_by%5D=date_posted",
)

# Backwards compatibility for callers that import LISTINGS_URL.
LISTINGS_URL = LISTING_URLS[0]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def _clean_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not match:
        return None
    normalised = match.group(0).replace(",", "")
    try:
        return int(float(normalised))
    except ValueError:
        return None


def _clean_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_bed_bath(text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None

    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None

    segments = [seg.strip() for seg in re.split(r"[/|\n]", text) if seg.strip()]
    for segment in segments:
        lowered = segment.lower()
        if "studio" in lowered:
            bedrooms = 0.0
            continue

        value = _clean_float(segment)
        if value is None:
            continue

        if any(token in lowered for token in ("bed", "bd", "br")):
            bedrooms = value
        elif any(token in lowered for token in ("bath", "ba")):
            bathrooms = value
        elif bedrooms is None:
            bedrooms = value
        elif bathrooms is None:
            bathrooms = value

    return bedrooms, bathrooms


def _extract_rent(container: BeautifulSoup) -> Optional[int]:
    rent_el = container.select_one(".js-listing-blurb-rent")
    if rent_el:
        return _clean_price(rent_el.get_text(" ", strip=True))

    for item in container.select(".detail-box__item"):
        label = item.select_one(".detail-box__label")
        if label and "rent" in label.get_text(strip=True).lower():
            value_el = item.select_one(".detail-box__value")
            if value_el:
                return _clean_price(value_el.get_text(" ", strip=True))
    return None


def _extract_beds_baths(container: BeautifulSoup) -> Tuple[Optional[float], Optional[float]]:
    text_el = container.select_one(".js-listing-blurb-bed-bath")
    if text_el:
        return _parse_bed_bath(text_el.get_text(" ", strip=True))

    for item in container.select(".detail-box__item"):
        label = item.select_one(".detail-box__label")
        if label and "bed" in label.get_text(strip=True).lower():
            value_el = item.select_one(".detail-box__value")
            if value_el:
                return _parse_bed_bath(value_el.get_text(" ", strip=True))

    return None, None


def _get_first_text(container: BeautifulSoup, selectors: Tuple[str, ...]) -> Optional[str]:
    for selector in selectors:
        element = container.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            if text:
                return text
    return None


def _extract_address(container: BeautifulSoup) -> Optional[str]:
    address = _get_first_text(
        container,
        (
            "[data-testid='listing-card-address']",
            "[data-testid='listingCard-address']",
            ".listing-card__address",
            ".listing-card__title",
            ".property-address",
            ".js-listing-address",
            ".listing-item__address",
            ".listing-item__title a",
            ".listing-item__title",
        ),
    )

    if not address:
        attr_value = container.get("data-address") or container.get("data-street")
        if isinstance(attr_value, str) and attr_value.strip():
            address = attr_value.strip()

    return address


def _extract_rent_appfolio(container: BeautifulSoup) -> Optional[int]:
    rent_text = _get_first_text(
        container,
        (
            "[data-testid='listing-card-rent']",
            "[data-testid='listingCard-rent']",
            ".listing-card__rent",
            ".listing-card__price",
            ".property-rent",
        ),
    )

    if rent_text:
        cleaned = _clean_price(rent_text)
        if cleaned is not None:
            return cleaned

    # Fallback to existing extraction for legacy markup.
    rent = _extract_rent(container)
    if rent is not None:
        return rent

    for text in container.stripped_strings:
        if "$" in text:
            cleaned = _clean_price(text)
            if cleaned is not None:
                return cleaned
    return None


def _extract_beds_baths_appfolio(container: BeautifulSoup) -> Tuple[Optional[float], Optional[float]]:
    bed_bath_text = _get_first_text(
        container,
        (
            "[data-testid='listing-card-bed-bath']",
            "[data-testid='listingCard-bedBath']",
            ".listing-card__bed-bath",
            ".listing-card__details",
            ".property-beds-baths",
        ),
    )

    if bed_bath_text:
        parsed = _parse_bed_bath(bed_bath_text)
        if parsed != (None, None):
            return parsed

    parsed = _extract_beds_baths(container)
    if parsed != (None, None):
        return parsed

    for text in container.stripped_strings:
        lowered = text.lower()
        if any(token in lowered for token in ("bed", "bath", "studio")):
            parsed = _parse_bed_bath(text)
            if parsed != (None, None):
                return parsed
    return None, None


def _parse_listing(container: BeautifulSoup, base_url: str) -> Optional[Unit]:
    link = (
        container.select_one("a[href*='/listings/detail']")
        or container.select_one("a[href*='/listings/']")
        or container.select_one("a[href]")
    )
    href = link.get("href") if link else None
    source_url = urljoin(base_url, href) if href else base_url

    address = _extract_address(container)
    rent = _extract_rent_appfolio(container)
    bedrooms, bathrooms = _extract_beds_baths_appfolio(container)

    if not address and not source_url:
        return None

    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=None,
        source_url=source_url,
    )


def parse_listings(html: str, *, base_url: str = LISTINGS_URL) -> List[Unit]:
    soup = BeautifulSoup(html, "lxml")

    container_selectors = (
        "[data-testid='listing-card']",
        "[data-testid='listingCard']",
        "div.listing-card",
        "div.listings__item",
        "li.listings__item",
        "div.property-item",
        "div.listing-item",
    )

    containers = []
    seen = set()
    for selector in container_selectors:
        for node in soup.select(selector):
            identifier = id(node)
            if identifier in seen:
                continue
            seen.add(identifier)
            containers.append(node)

    if not containers:
        # Fallback: treat anchors pointing to listings as potential containers.
        containers = []
        for anchor in soup.select("a[href*='/listings']"):
            parent = anchor.parent
            containers.append(parent or anchor)

    logger.debug(
        "Anchor Realty parser located %d potential listing containers", len(containers)
    )

    units: List[Unit] = []
    for idx, container in enumerate(containers):
        unit = _parse_listing(container, base_url=base_url)
        if unit:
            if idx < 3:
                logger.debug(
                    "Anchor Realty sample listing %d: address=%s rent=%s bedrooms=%s",
                    idx,
                    unit.address,
                    unit.rent,
                    unit.bedrooms,
                )
            units.append(unit)
    return units


def fetch_units(
    urls: Optional[Union[str, List[str], Tuple[str, ...]]] = None, *, timeout: int = 20
) -> List[Unit]:
    if urls is None:
        url_list = list(LISTING_URLS)
    elif isinstance(urls, str):
        url_list = [urls]
    else:
        url_list = list(urls)

    units: List[Unit] = []
    for url in url_list:
        logger.debug("Fetching Anchor Realty listings from %s", url)
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        logger.debug(
            "Anchor Realty HTTP %s (%d bytes)", response.status_code, len(response.content)
        )
        units.extend(parse_listings(response.text, base_url=url))

    return units


fetch_units.default_url = LISTINGS_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_listings"]
