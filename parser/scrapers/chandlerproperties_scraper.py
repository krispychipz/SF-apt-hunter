"""Scraper for Chandler Properties rental listings."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from parser.models import Unit

LISTINGS_URL = "https://chandlerproperties.com/rental-listings/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://chandlerproperties.com/",
    "Accept-Encoding": "gzip, deflate, br",
}

def get_html(url: str, client: httpx.Client, referer: Optional[str] = None) -> str:
    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer
    # Optionally, you can set cookies here if needed
    for attempt in range(3):
        r = client.get(url, headers=headers, timeout=httpx.Timeout(20.0))
        if r.status_code == 200:
            # Save cookies for subsequent requests
            if r.cookies:
                client.cookies.update(r.cookies)
            return r.text
        if r.status_code in (403, 429, 503):
            import time, random
            time.sleep(1.0 + attempt + random.uniform(0, 0.5))
            continue
        r.raise_for_status()
    # final try or raise
    r = client.get(url, headers=headers, timeout=httpx.Timeout(20.0))
    r.raise_for_status()
    if r.cookies:
        client.cookies.update(r.cookies)
    return r.text

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
    client = httpx.Client(http2=True, follow_redirects=True, headers=HEADERS)
    # Warm up: initial request to set cookies
    landing_html = get_html(LISTINGS_URL, client)
    # Main request with referer and cookies
    html = get_html(url, client, referer=LISTINGS_URL if url != LISTINGS_URL else None)
    return parse_listings(html, base_url=url)

fetch_units.default_url = LISTINGS_URL  # Add this line after defining fetch_units

__all__ = ["fetch_units", "parse_listings"]