"""Scraper for RentBT San Francisco two-bedroom listings."""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from parser.heuristics import money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit
from .rentbt_scraper import apply_filter_params as _base_apply_filter_params

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

BASE_URL = (
    "https://properties.rentbt.com/searchlisting.aspx?ftst=&txtCity=san%20francisco"
    "&txtMinRent=3000&txtMaxRent=4000&cmbBeds=2&txtDistance=3&LocationGeoId=0"
    "&zoom=10&autoCompleteCorpPropSearchlen=3&renewpg=1&PgNo=1"
    "&LatLng=(37.7749295,-122.4194155)&"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
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
    # Add client hints often requested by CF (match UA)
    "sec-ch-ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \";Not A Brand\";v=\"99\"",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-arch": "\"x86\"",
    "sec-ch-ua-bitness": "\"64\"",
    "sec-ch-ua-full-version": "\"124.0.6367.91\"",
    "sec-ch-ua-full-version-list": "\"Chromium\";v=\"124.0.6367.91\", \"Google Chrome\";v=\"124.0.6367.91\", \";Not A Brand\";v=\"99.0.0.0\"",
}

MINIMAL_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": HEADERS["Accept-Language"],
    "Connection": HEADERS["Connection"],
}

HEADER_PROFILES = {
    "full": HEADERS,
    "minimal": MINIMAL_HEADERS,
}

LANDING_URL = "https://properties.rentbt.com/"
SEARCH_FORM_URL = requests.compat.urljoin(LANDING_URL, "searchlisting.aspx")

_SCRIPT_ASSIGNMENT_PATTERNS = (
    (
        re.compile(
            r"getElementById\(['\"](?P<name>[^'\"]+)['\"]\)\.value\s*=\s*['\"](?P<value>[^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\$\(['\"][#.]?(?P<name>[^'\"]+)['\"]\)\.val\(['\"](?P<value>[^'\"]+)['\"]\)",
            re.IGNORECASE,
        ),
        True,
    ),
    (
        re.compile(
            r"\b(?P<name>ftst)\b\s*[:=]\s*['\"](?P<value>[^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        False,
    ),
)


def _clean_numeric(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text)


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


def _resolve_headers(profile: str = "full", overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = HEADER_PROFILES.get(profile, HEADERS).copy()
    if overrides:
        headers.update({k: v for k, v in overrides.items() if v})
    return headers


def _set_headers(session: Any, headers: Dict[str, str]) -> None:
    if hasattr(session, "headers"):
        try:
            session.headers.update(headers)
        except Exception:  # pragma: no cover - defensive
            pass


def set_page_number(url: str, page: int) -> str:
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


def _cookie_snapshot(source: Any) -> Dict[str, str]:
    if not source:
        return {}
    try:
        return dict(source)
    except TypeError:  # pragma: no cover - defensive
        try:
            return requests.utils.dict_from_cookiejar(source)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            return {}


def _emit_debug(
    hook: Optional[Callable[[str, Dict[str, Any]], None]],
    phase: str,
    payload: Dict[str, Any],
) -> None:
    if not hook:
        return
    try:
        hook(phase, payload)
    except Exception:  # pragma: no cover - defensive
        pass


def _merge_query_params(url: str, params: Dict[str, str]) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    changed = False
    for key, value in params.items():
        if not value:
            continue
        if query.get(key) != [value]:
            query[key] = [value]
            changed = True
    if not changed:
        return url
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
    headers: Optional[Dict[str, str]] = None,
    retries: int = 1,
    delay: float = 0.8,
) -> str:
    request_headers = (headers or HEADERS).copy()
    if referer:
        request_headers["Referer"] = referer
    attempt = 0
    last_exc = None
    while attempt <= retries:
        attempt += 1
        if httpx is not None and isinstance(client, httpx.Client):  # type: ignore[arg-type]
            response = client.get(url, headers=request_headers, timeout=httpx.Timeout(timeout))
        else:
            response = client.get(url, headers=request_headers, timeout=timeout)
        if response.status_code == 403 and "cf-mitigated" in {k.lower(): v for k, v in response.headers.items()}:
            # Cloudflare challenge; try once more after short delay
            last_exc = Exception(f"403 Cloudflare challenge (attempt {attempt})")
            if attempt <= retries:
                time.sleep(delay)
                continue
            response.raise_for_status()
        response.raise_for_status()
        if hasattr(response, "cookies") and hasattr(client, "cookies"):
            client.cookies.update(response.cookies)  # type: ignore[attr-defined]
        return response.text
    raise last_exc or RuntimeError("Failed to fetch page")


def _parse_address(listing: BeautifulSoup) -> Optional[str]:
    hidden = listing.select_one(".parameters .propertyAddress")
    if hidden:
        address = _clean_numeric(hidden.get_text())
        if address:
            return address
    parts: List[str] = []
    for selector in ("propertyAddress", "propertyCity", "propertyState", "propertyZipCode"):
        element = listing.select_one(f".prop-address .{selector}")
        if not element:
            continue
        text = element.get_text(strip=True)
        if text:
            parts.append(re.sub(r"\s+", " ", text))
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
    containers = soup.select("div.resultBody div.property-details.prop-listing-box")
    if not containers:
        containers = soup.select("div.property-details.prop-listing-box")

    listings: List[Unit] = []
    for container in containers:
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


def parse_search_form_tokens(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    tokens: Dict[str, str] = {}
    for element in soup.select("input[type='hidden'][name]"):
        name = element.get("name")
        value = element.get("value")
        if not name or not value:
            continue
        tokens[name] = value

    script_texts: List[str] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if text:
            script_texts.append(text)
    if script_texts:
        merged = "\n".join(script_texts)
        for pattern, allow_override in _SCRIPT_ASSIGNMENT_PATTERNS:
            for match in pattern.finditer(merged):
                name = match.group("name")
                value = match.group("value")
                if not name or not value:
                    continue
                if name.startswith("#") or name.startswith("."):
                    name = name[1:]
                if tokens.get(name) and not allow_override:
                    continue
                tokens[name] = value
    return tokens


def _load_search_form_tokens(
    *,
    client: Any,
    timeout: int = 20,
    referer: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    html = _get_page(
        SEARCH_FORM_URL,
        client=client,
        timeout=timeout,
        referer=referer,
        headers=headers,
    )
    return parse_search_form_tokens(html)


def fetch_units(
    url: str = BASE_URL,
    *,
    pages: int = 1,
    delay: float = 1.0,
    session: Optional[Any] = None,
    timeout: int = 20,
    debug: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    header_profile: str = "full",
    header_overrides: Optional[Dict[str, str]] = None,
) -> List[Unit]:
    headers = _resolve_headers(header_profile, header_overrides)
    if session is not None:
        http_session = session
        close_session = lambda: None
        _set_headers(http_session, headers)
    else:
        # Disable HTTP/2 to reduce CF scrutiny
        if httpx is not None:
            http_session = httpx.Client(
                http2=False,
                follow_redirects=True,
                headers=headers,
                timeout=httpx.Timeout(timeout),
            )
            close_session = http_session.close
        else:  # pragma: no cover - fallback without httpx
            http_session = requests.Session()
            _set_headers(http_session, headers)
            close_session = http_session.close

    all_units: List[Unit] = []

    try:
        _emit_debug(
            debug,
            "session_headers",
            {
                "profile": header_profile,
                "headers": headers.copy(),
            },
        )

        try:  # warm-up request for cookies/session state
            _get_page(
                LANDING_URL,
                client=http_session,
                timeout=timeout,
                headers=headers,
            )
        except Exception:
            pass
        else:
            _emit_debug(
                debug,
                "warmup",
                {
                    "url": LANDING_URL,
                    "cookies": _cookie_snapshot(getattr(http_session, "cookies", None)),
                },
            )

        try:
            tokens = _load_search_form_tokens(
                client=http_session,
                timeout=timeout,
                referer=LANDING_URL,
                headers=headers,
            )
        except Exception:
            tokens = {}

        url = _merge_query_params(url, tokens)
        referer: Optional[str] = SEARCH_FORM_URL if tokens else LANDING_URL

        _emit_debug(
            debug,
            "tokens",
            {
                "tokens": tokens.copy(),
                "merged_url": url,
            },
        )

        for page in range(1, max(1, pages) + 1):
            page_url = set_page_number(url, page)
            html = _get_page(
                page_url,
                client=http_session,
                timeout=timeout,
                referer=referer,
                headers=headers,
            )
            units = parse_listings(html, base_url=url)
            if not units and page > 1:
                break
            all_units.extend(units)
            _emit_debug(
                debug,
                "page",
                {
                    "page": page,
                    "url": page_url,
                    "unit_count": len(units),
                    "cookies": _cookie_snapshot(getattr(http_session, "cookies", None)),
                },
            )
            if delay:
                time.sleep(delay)
            referer = page_url
    finally:
        if session is None:
            close_session()

    return all_units


fetch_units.default_url = BASE_URL  # type: ignore[attr-defined]
fetch_units.apply_filter_params = _base_apply_filter_params  # type: ignore[attr-defined]

apply_filter_params = _base_apply_filter_params


__all__ = [
    "BASE_URL",
    "apply_filter_params",
    "fetch_units",
    "parse_listings",
    "parse_search_form_tokens",
    "set_page_number",
]
