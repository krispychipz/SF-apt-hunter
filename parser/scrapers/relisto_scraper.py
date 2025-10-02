"""Scraper for Relisto rental listings."""

from __future__ import annotations

import re
import time
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from parser.models import Unit

BASE_URL = "https://www.relisto.com/search/unfurnished/"

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


def clean_price(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", value)
    if not match:
        return None
    normalised = match.group(0).replace(",", "")
    try:
        return int(float(normalised))
    except ValueError:
        return None


def clean_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def set_page_number(url: str, page: int) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page <= 1:
        query.pop("sf_paged", None)
    else:
        query["sf_paged"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def _get_page(url: str, session: requests.Session, timeout: int = 20) -> str:
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_listings(html: str, *, base_url: str = BASE_URL) -> List[Unit]:
    soup = BeautifulSoup(html, "lxml")
    listings: List[Unit] = []

    for anchor in soup.select("a.listing-box"):
        href = anchor.get("href")
        url = requests.compat.urljoin(base_url, href) if href else None

        data_beds = anchor.get("data-beds")
        data_baths = anchor.get("data-baths")
        data_price = anchor.get("data-price")

        address: Optional[str] = None
        loc = anchor.select_one("h4.location")
        if loc and loc.get_text(strip=True):
            address = loc.get_text(strip=True)
        if address is None and href and "/rentals/" in href:
            slug = href.rstrip("/").split("/")[-1]
            address = slug.replace("-", " ").title()

        beds = clean_float(data_beds) if data_beds else None
        if beds is None:
            beds_el = anchor.select_one(".item-beds .item-value")
            beds = clean_float(beds_el.get_text(strip=True)) if beds_el else None

        baths = clean_float(data_baths) if data_baths else None
        if baths is None:
            baths_el = anchor.select_one(".item-baths .item-value")
            baths = clean_float(baths_el.get_text(strip=True)) if baths_el else None

        price = clean_price(data_price) if data_price else None
        if price is None:
            price_el = anchor.select_one(".item-price .item-value")
            price = clean_price(price_el.get_text(strip=True)) if price_el else None

        if not address and not price and not url:
            continue

        listings.append(
            Unit(
                address=address,
                bedrooms=beds,
                bathrooms=baths,
                rent=price,
                neighborhood=None,
                source_url=url or base_url,
            )
        )

    return listings


def fetch_units(
    url: str = BASE_URL,
    *,
    pages: int = 1,
    delay: float = 1.0,
    session: Optional[requests.Session] = None,
    timeout: int = 20,
) -> List[Unit]:
    """Fetch Relisto listings from *url*, walking pagination up to *pages*."""

    http_session = session or requests.Session()
    all_units: List[Unit] = []

    for page in range(1, max(1, pages) + 1):
        page_url = set_page_number(url, page)
        html = _get_page(page_url, session=http_session, timeout=timeout)
        units = parse_listings(html, base_url=url)
        if not units and page > 1:
            break
        all_units.extend(units)
        if delay:
            time.sleep(delay)

    return all_units


__all__ = ["fetch_units", "parse_listings", "set_page_number"]
