"""Scraper for Chandler Properties rental listings."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit

LISTINGS_URL = "https://chandlerproperties.com/rental-listings/"

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


def _parse_listing(container: BeautifulSoup, base_url: str) -> Optional[Unit]:
    anchor = container.select_one("a[href]")
    href = anchor.get("href") if anchor else None
    source_url = urljoin(base_url, href) if href else base_url

    address_el = container.select_one(".address")
    address = address_el.get_text(strip=True) if address_el else None

    rent_el = container.select_one(".rent-price")
    rent = _clean_price(rent_el.get_text(strip=True)) if rent_el else None

    beds_el = container.select_one(".beds")
    bedrooms = _clean_float(beds_el.get_text(" ", strip=True)) if beds_el else None

    baths_el = container.select_one(".baths")
    bathrooms = _clean_float(baths_el.get_text(" ", strip=True)) if baths_el else None

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


__all__ = ["fetch_units", "parse_listings"]
