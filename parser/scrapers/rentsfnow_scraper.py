"""Scraper for RentSFNow rental listings."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from parser.heuristics import money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

AJAX_ENDPOINT = "https://www.rentsfnow.com/wp-admin/admin-ajax.php"
DEFAULT_URL = "https://www.rentsfnow.com/apartments/rentals/"

HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Origin": "https://www.rentsfnow.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

_DEFAULT_PAYLOAD: Dict[str, str] = {
    "action": "filter_properties",
    "property_type": "rental",
    "region": "",
    "bedrooms": "",
    "neighborhood": "",
    "min_price": "",
    "max_price": "",
    "paged": "1",
}


def _ensure_absolute(url: str) -> str:
    if not url:
        return DEFAULT_URL
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url
    return urljoin(DEFAULT_URL, url)


def _extract_unit_details(blocks: Iterable[BeautifulSoup]) -> Tuple[
    Optional[float],
    Optional[float],
    Optional[int],
]:
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    rent: Optional[int] = None

    for block in blocks:
        text = block.get_text(" ", strip=True)
        if not text:
            continue
        if bedrooms is None:
            bedrooms = parse_bedrooms(text)
        if bathrooms is None:
            bathrooms = parse_bathrooms(text)
        if rent is None:
            rent = money_to_int(text)
        if bedrooms is not None and bathrooms is not None and rent is not None:
            break

    return bedrooms, bathrooms, rent


def parse_listings(html: str, *, base_url: str = DEFAULT_URL) -> List[Unit]:
    """Parse RentSFNow listing markup into :class:`Unit` objects."""

    soup = BeautifulSoup(html, "lxml")
    containers = soup.select("div.searchDetailSpacing")

    units: List[Unit] = []
    for container in containers:
        anchor = container.find("a", href=True)
        href = anchor["href"] if anchor else None
        source_url = urljoin(base_url, href) if href else base_url

        neighborhood_el = container.select_one("h3")
        neighborhood = neighborhood_el.get_text(strip=True) if neighborhood_el else None

        address_el = container.select_one("h2")
        address = address_el.get_text(strip=True) if address_el else None

        info_blocks = container.select("p.apartment-info")
        bedrooms, bathrooms, rent = _extract_unit_details(info_blocks)

        if not address and not href:
            continue

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


def build_payload(url: str) -> Tuple[Dict[str, str], str]:
    """Return POST payload and referer derived from *url*."""

    referer = _ensure_absolute(url)
    payload = _DEFAULT_PAYLOAD.copy()

    parsed = urlparse(referer)
    query = parse_qs(parsed.query, keep_blank_values=True)

    aliases = {
        "beds": "bedrooms",
        "bedrooms": "bedrooms",
        "min_price": "min_price",
        "min_rent": "min_price",
        "max_price": "max_price",
        "max_rent": "max_price",
        "neighborhood": "neighborhood",
        "region": "region",
        "page": "paged",
        "paged": "paged",
    }

    for key, values in query.items():
        if not values:
            continue
        canonical = aliases.get(key.lower())
        if not canonical:
            continue
        payload[canonical] = values[-1]

    return payload, referer


def _prepare_headers(referer: str) -> Dict[str, str]:
    headers = HEADERS.copy()
    headers["Referer"] = referer
    parsed = urlparse(referer)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.rentsfnow.com"
    headers["Origin"] = origin
    return headers


def fetch_units(
    url: str = DEFAULT_URL,
    *,
    timeout: int = 20,
    session: Optional[Any] = None,
) -> List[Unit]:
    """Fetch RentSFNow listings and parse them into :class:`Unit` objects."""

    payload, referer = build_payload(url)
    headers = _prepare_headers(referer)

    close_session = False
    client: Any

    if session is not None:
        client = session
    elif httpx is not None:  # pragma: no cover - optional dependency path
        client = httpx.Client(  # type: ignore[no-untyped-call]
            http2=True,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),  # type: ignore[attr-defined]
        )
        close_session = True
    else:
        client = requests.Session()
        close_session = True

    try:
        if hasattr(client, "headers"):
            try:
                client.headers.update({k: v for k, v in HEADERS.items() if k not in {"Origin"}})
            except Exception:  # pragma: no cover - defensive
                pass

        if httpx is not None and isinstance(client, httpx.Client):  # type: ignore[arg-type]
            response = client.post(
                AJAX_ENDPOINT,
                data=payload,
                headers=headers,
                timeout=httpx.Timeout(timeout),  # type: ignore[attr-defined]
            )
        else:
            response = client.post(AJAX_ENDPOINT, data=payload, headers=headers, timeout=timeout)

        response.raise_for_status()
        html = response.text
        return parse_listings(html, base_url=referer)
    finally:
        if close_session:
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive
                pass


def apply_filter_params(
    url: str,
    *,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[Iterable[str]] = None,
    **_: Any,
) -> str:
    """Embed filter parameters into the RentSFNow listings URL."""

    absolute = _ensure_absolute(url)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query, keep_blank_values=True)
    changed = False

    if max_rent is not None:
        query["max_price"] = [str(int(max_rent))]
        changed = True

    if min_bedrooms is not None:
        bedrooms_value = str(int(math.ceil(min_bedrooms)))
        query["bedrooms"] = [bedrooms_value]
        changed = True

    if neighborhoods:
        first = next((name.strip() for name in neighborhoods if name and name.strip()), "")
        if first:
            query["neighborhood"] = [first]
            changed = True

    if not changed:
        return absolute

    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


fetch_units.default_url = DEFAULT_URL  # type: ignore[attr-defined]
fetch_units.apply_filter_params = apply_filter_params  # type: ignore[attr-defined]

__all__ = [
    "AJAX_ENDPOINT",
    "DEFAULT_URL",
    "apply_filter_params",
    "build_payload",
    "fetch_units",
    "parse_listings",
]

