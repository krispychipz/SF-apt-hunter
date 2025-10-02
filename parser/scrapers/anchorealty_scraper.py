"""Scraper for Anchor Realty rental listings."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit

LISTINGS_URL = "https://anchorealtyinc.com/residential-rentals/"

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


def _parse_listing(container: BeautifulSoup, base_url: str) -> Optional[Unit]:
    link = container.select_one("a[href*='/listings/detail']") or container.select_one("a[href]")
    href = link.get("href") if link else None
    source_url = urljoin(base_url, href) if href else base_url

    address: Optional[str] = None
    for selector in (
        ".js-listing-address",
        ".listing-item__address",
        ".listing-item__title a",
        ".listing-item__title",
    ):
        address_el = container.select_one(selector)
        if address_el and address_el.get_text(strip=True):
            address = address_el.get_text(strip=True)
            break

    rent = _extract_rent(container)
    bedrooms, bathrooms = _extract_beds_baths(container)

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

    units: List[Unit] = []
    for container in soup.select("div.listing-item"):
        unit = _parse_listing(container, base_url=base_url)
        if unit:
            units.append(unit)
    return units


def fetch_units(url: str = LISTINGS_URL, *, timeout: int = 20) -> List[Unit]:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return parse_listings(response.text, base_url=url)


fetch_units.default_url = LISTINGS_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_listings"]
