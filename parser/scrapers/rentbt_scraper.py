"""Scraper for RentBT (rentbt.com) property listings."""

from __future__ import annotations

import time
from typing import Any, List, Optional

import requests
from bs4 import BeautifulSoup

from parser.heuristics import money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

BASE_URL = (
    "https://properties.rentbt.com/searchlisting.aspx?ftst=&txtCity=san%20francisco"
    "&txtMinRent=3000&txtMaxRent=4000&cmbBeds=2&txtDistance=2&LocationGeoId=0"
    "&zoom=10&autoCompleteCorpPropSearchlen=3&renewpg=1&PgNo=1"
    "&LatLng=(37.7749295,-122.4194155)&"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

LANDING_URL = "https://properties.rentbt.com/"


def _clean_rent(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = value.strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def set_page_number(url: str, page: int) -> str:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page <= 1:
        query.pop("PgNo", None)
    else:
        query["PgNo"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def _get_page(
    url: str,
    *,
    client: Any,
    timeout: int = 20,
    referer: Optional[str] = None,
) -> str:
    headers = HEADERS.copy()
    referer_header = referer or LANDING_URL
    if referer_header:
        headers["Referer"] = referer_header

    if httpx is not None and isinstance(client, httpx.Client):  # type: ignore[arg-type]
        response = client.get(url, headers=headers, timeout=httpx.Timeout(timeout))
    else:
        response = client.get(url, headers=headers, timeout=timeout)

    response.raise_for_status()

    if hasattr(response, "cookies") and hasattr(client, "cookies"):
        client.cookies.update(response.cookies)

    return response.text


def _parse_address(listing: BeautifulSoup) -> Optional[str]:
    hidden = listing.select_one(".parameters .propertyAddress")
    if hidden and hidden.get_text(strip=True):
        return " ".join(hidden.get_text(strip=True).split())

    parts: List[str] = []
    for selector in (".propertyAddress", ".propertyCity", ".propertyState", ".propertyZipCode"):
        element = listing.select_one(f".prop-address {selector}")
        if element and element.get_text(strip=True):
            parts.append(" ".join(element.get_text(strip=True).split()))
    if parts:
        return " ".join(parts)
    return None


def _parse_bedrooms(listing: BeautifulSoup) -> Optional[float]:
    for selector in (".propertyMaxBed", ".propertyMinBed"):
        element = listing.select_one(selector)
        if element and element.get_text(strip=True):
            beds = parse_bedrooms(f"{element.get_text(strip=True)} bed")
            if beds is not None:
                return beds

    beds_el = listing.select_one(".prop-beds")
    if beds_el and beds_el.get_text(strip=True):
        beds = parse_bedrooms(beds_el.get_text(" ", strip=True))
        if beds is not None:
            return beds

    return None


def _parse_bathrooms(listing: BeautifulSoup) -> Optional[float]:
    baths_el = listing.select_one(".prop-baths")
    if baths_el and baths_el.get_text(strip=True):
        baths = parse_bathrooms(baths_el.get_text(" ", strip=True))
        if baths is not None:
            return baths

    element = listing.select_one(".propertyMinBath")
    if element and element.get_text(strip=True):
        return parse_bathrooms(f"{element.get_text(strip=True)} bath")
    return None


def _parse_rent(listing: BeautifulSoup) -> Optional[int]:
    hidden = listing.select_one(".parameters .propertyMinRent")
    if hidden and hidden.get_text(strip=True):
        rent = _clean_rent(hidden.get_text(strip=True))
        if rent is not None:
            return rent

    display = listing.select_one(".prop-rent")
    if display and display.get_text(strip=True):
        rent = money_to_int(display.get_text(" ", strip=True))
        if rent is not None:
            return rent

    element = listing.select_one(".propertyMaxRent")
    if element and element.get_text(strip=True):
        return _clean_rent(element.get_text(strip=True))
    return None


def parse_listings(html: str, *, base_url: str = BASE_URL) -> List[Unit]:
    soup = BeautifulSoup(html, "lxml")
    listings: List[Unit] = []

    for container in soup.select("div.property-details.prop-listing-box"):
        address = _parse_address(container)
        rent = _parse_rent(container)
        bedrooms = _parse_bedrooms(container)
        bathrooms = _parse_bathrooms(container)

        anchor = container.select_one("a.propertyUrl")
        href = anchor.get("href") if anchor else None
        url = requests.compat.urljoin(base_url, href) if href else base_url

        if not (address or rent or href):
            continue

        listings.append(
            Unit(
                address=address,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                rent=rent,
                neighborhood=None,
                source_url=url,
            )
        )

    return listings


def fetch_units(
    url: str = BASE_URL,
    *,
    pages: int = 1,
    delay: float = 1.0,
    session: Optional[Any] = None,
    timeout: int = 20,
) -> List[Unit]:
    """Fetch RentBT listings from *url*, iterating pagination up to *pages*."""

    if session is not None:
        http_session = session
        close_session = lambda: None
        if hasattr(http_session, "headers"):
            try:
                http_session.headers.update(HEADERS)
            except Exception:
                pass
    else:
        if httpx is not None:
            http_session = httpx.Client(
                http2=True,
                follow_redirects=True,
                headers=HEADERS,
                timeout=httpx.Timeout(timeout),
            )
            close_session = http_session.close
        else:  # pragma: no cover - fallback without httpx
            http_session = requests.Session()
            http_session.headers.update(HEADERS)
            close_session = http_session.close

    all_units: List[Unit] = []

    try:
        # Initial landing request to establish cookies and session state.
        try:
            _get_page(LANDING_URL, client=http_session, timeout=timeout)
        except Exception:
            # Ignore warm-up failures; the main requests will raise if necessary.
            pass

        referer: Optional[str] = LANDING_URL

        for page in range(1, max(1, pages) + 1):
            page_url = set_page_number(url, page)
            html = _get_page(
                page_url,
                client=http_session,
                timeout=timeout,
                referer=referer,
            )
            units = parse_listings(html, base_url=url)
            if not units and page > 1:
                break
            all_units.extend(units)
            if delay:
                time.sleep(delay)

            referer = page_url

    finally:
        if session is None:
            close_session()

    return all_units


fetch_units.default_url = BASE_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_listings", "set_page_number"]
