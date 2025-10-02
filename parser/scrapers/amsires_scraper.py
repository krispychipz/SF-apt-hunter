"""Scraper for AMS IRES rental listings."""

from __future__ import annotations

import re
import logging
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit


logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.amsires.com/unfurnished-rentals-search"

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
    m = re.search(r"[\\$\\s]*([\\d,]+(?:\\.\\d+)?)", text)
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
    m = re.search(r"\\d+(?:\\.\\d+)?", text)
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


def fetch_units(url: str = SEARCH_URL, *, timeout: int = 20) -> List[Unit]:
    """Fetch and parse AMS IRES listings from *url*."""

    logger.debug("Fetching AMS IRES listings from %s", url)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    logger.debug("AMS IRES HTTP %s (%d bytes)", response.status_code, len(response.content))
    return parse_listings(response.text, base_url=url)


fetch_units.default_url = SEARCH_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_listings"]
