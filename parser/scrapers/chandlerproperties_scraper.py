"""Scraper for Chandler Properties rental listings."""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parser.models import Unit

logger = logging.getLogger(__name__)
for name in ("httpx", "httpcore"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # optional: stop passing to root handlers
try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

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


def get_html(url: str, client: Any, referer: Optional[str] = None) -> str:
    """Fetch *url* with retry logic and optional *referer* header."""

    headers = HEADERS.copy()
    if referer:
        headers["Referer"] = referer

    logger.debug("Chandler Properties request %s (referer=%s)", url, referer)

    for attempt in range(3):
        timeout = httpx.Timeout(20.0) if httpx else 20.0  # type: ignore[union-attr]
        response = client.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            if response.cookies:
                client.cookies.update(response.cookies)
            logger.debug(
                "Chandler Properties HTTP %s on attempt %d (%d bytes)",
                response.status_code,
                attempt + 1,
                len(response.content),
            )
            return response.text

        if response.status_code in (403, 429, 503):
            import random
            import time

            time.sleep(1.0 + attempt + random.uniform(0, 0.5))
            continue

        response.raise_for_status()

    # Final attempt will either succeed or raise.
    timeout = httpx.Timeout(20.0) if httpx else 20.0  # type: ignore[union-attr]
    response = client.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    logger.debug(
        "Chandler Properties final retry HTTP %s (%d bytes)",
        response.status_code,
        len(response.content),
    )
    if response.cookies:
        client.cookies.update(response.cookies)
    return response.text


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

    containers = soup.select("div.listing-item")
    logger.debug("Chandler Properties parser located %d potential listing containers", len(containers))

    units: List[Unit] = []
    for idx, container in enumerate(containers):
        unit = _parse_listing(container, base_url=base_url)
        if unit:
            if idx < 3:
                logger.debug(
                    "Chandler Properties sample listing %d: address=%s rent=%s bedrooms=%s",
                    idx,
                    unit.address,
                    unit.rent,
                    unit.bedrooms,
                )
            units.append(unit)

    return units


def fetch_units(url: str = LISTINGS_URL, *, timeout: int = 20) -> List[Unit]:
    if httpx is not None:
        client = httpx.Client(
            http2=True,
            follow_redirects=True,
            headers=HEADERS,
            timeout=httpx.Timeout(timeout),
        )
        close_client = client.close
    else:  # pragma: no cover - fallback path
        client = requests.Session()
        client.headers.update(HEADERS)
        close_client = client.close

    try:
        # Warm up: initial request to set cookies
        landing_html = get_html(LISTINGS_URL, client)
        logger.debug("Chandler Properties warm-up fetched %d bytes", len(landing_html))

        # Main request with referer and cookies
        # referer = LISTINGS_URL if url != LISTINGS_URL else None
        # html = get_html(url, client, referer=referer)
        return parse_listings(landing_html, base_url=url)
    finally:
        close_client()


fetch_units.default_url = LISTINGS_URL  # type: ignore[attr-defined]

__all__ = ["fetch_units", "parse_listings"]
