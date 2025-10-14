"""Scraper for RentSFNow rental listings."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
import logging
import requests
from bs4 import BeautifulSoup
import re

from parser.heuristics import money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    httpx = None  # type: ignore

AJAX_ENDPOINT = "https://www.rentsfnow.com/wp-admin/admin-ajax.php"
DEFAULT_URL = "https://www.rentsfnow.com/apartments/sf/"

HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# Neighborhood -> ZIP mapping (scoped to this scraper only)
_NEIGHBORHOOD_ZIP_MAP: Dict[str, Set[str]] = {
    "downtown": {"94103"},
    "soma": {"94103"},
    "nopa": {"94117"},
    "western addition": {"94115", "94117"},
    "lower pacific heights": {"94115"},
    "pacific heights": {"94109", "94115"},
    "russian hill": {"94109"},
    "nob hill": {"94108", "94109"},
    "tenderloin": {"94102"},
    "mission": {"94110"},
    "inner sunset": {"94122"},
    "outer sunset": {"94122"},
    "richmond": {"94118", "94121"},
    "lower haight": {"94117"},
    "upper haight": {"94117"},
    "haight ashbury": {"94117"},
    "hayes valley": {"94102", "94103"},
}

_ZIP_RE = re.compile(r"\b94\d{3}\b")

def _neighborhood_matches_zip(neighborhood: Optional[str], allowed: Set[str]) -> bool:
    if not allowed:
        return True
    if not neighborhood:
        return False
    zset = _NEIGHBORHOOD_ZIP_MAP.get(neighborhood.strip().lower())
    if not zset:
        return False
    return not zset.isdisjoint(allowed)

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


def _build_ajax_payload(
    *,
    min_price: Optional[int],
    max_price: Optional[int],
    bedrooms: Optional[float],
    neighborhood: Optional[str],
    page: int = 1,
) -> Dict[str, str]:
    """
    Build the payload that matches the working cURL:
    action=wpas_ajax_load&type=search
    """
    # Clamp / format values
    min_p = str(min_price) if min_price is not None else "0"
    max_p = str(max_price) if max_price is not None else ""
    price_range = f"{min_p},{max_p or ''}".rstrip(",")
    beds_val = str(int(bedrooms)) if bedrooms is not None else ""
    payload: Dict[str, str] = {
        "neighborhood": neighborhood or "",
        "city": "san-francisco",
        "price": price_range,
        "bedrooms": beds_val,
        "bathrooms": "",
        "withdishwasher": "",
        "in_unit_laundry": "",
        "furnished": "",
        "pets_cats_only": "",
        "pets_dogs_only": "",
        "minprice": min_p,
        "maxprice": max_p,
        "sort": "priority_value-desc",
        "view": "map",
        "comingsoon": "",
        "comingsoononly": "",
        "action": "wpas_ajax_load",
        "page": str(page),
        "type": "search",
    }
    return payload

def build_payload(url: str) -> Tuple[Dict[str, str], str]:
    """Derive payload from filters embedded in *url* query.

    Supported query params:
      bedrooms=2
      price=1500,5300   (preferred consolidated form)
      min_price / max_price (legacy)
      neighborhood=<slug>
      page / paged
    """
    referer = _ensure_absolute(url)
    parsed = urlparse(referer)
    qs = parse_qs(parsed.query, keep_blank_values=True)

    def _last(name: str) -> Optional[str]:
        v = qs.get(name)
        return v[-1] if v else None

    min_price = _last("min_price") or _last("minprice")
    max_price = _last("max_price") or _last("maxprice")
    price_range = _last("price")

    # If unified price range given and individual bounds absent, parse it
    if price_range and not (min_price or max_price):
        if "," in price_range:
            lo, hi = price_range.split(",", 1)
            lo = lo.strip()
            hi = hi.strip()
            if lo.isdigit():
                min_price = lo
            if hi.isdigit():
                max_price = hi
        else:
            # Single value interpreted as max
            if price_range.isdigit():
                max_price = price_range

    min_beds = _last("bedrooms") or _last("beds")
    hood = _last("neighborhood")

    min_price_i = int(min_price) if (min_price and min_price.isdigit()) else None
    max_price_i = int(max_price) if (max_price and max_price.isdigit()) else None
    beds_f = float(min_beds) if (min_beds and min_beds.isdigit()) else None

    payload = _build_ajax_payload(
        min_price=min_price_i,
        max_price=max_price_i,
        bedrooms=beds_f,
        neighborhood=hood,
        page=int(_last("page") or _last("paged") or "1"),
    )
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
    max_pages: int = 10,
    delay: float = 0.4,
    zip_codes: Optional[Iterable[str]] = None,   # NEW: optional ZIP filter
    **_: Any,  # absorb unused kwargs safely
) -> List[Unit]:
    """Fetch listings via the wpas_ajax_load endpoint with pagination.
       Optionally filter by ZIP codes derived from neighborhood labels.
    """
    payload, referer = build_payload(url)
    headers = _prepare_headers(referer)
    headers.update({
        "Accept": "text/html, */*; q=0.01",
        "DNT": "1",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    })

    allowed_zips: Set[str] = {z.strip() for z in zip_codes} if zip_codes else set()

    close_session = False
    if session is not None:
        client = session
    elif httpx is not None:
        client = httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(timeout))  # type: ignore
        close_session = True
    else:
        client = requests.Session()
        close_session = True

    try:
        try:
            client.get(referer, headers=headers, timeout=timeout)
        except Exception:
            pass

        all_units: List[Unit] = []
        seen_urls: set[str] = set()
        page = int(payload.get("page", "1") or "1")

        while page <= max_pages:
            payload["page"] = str(page)
            try:
                if httpx is not None and isinstance(client, httpx.Client):
                    resp = client.post(
                        AJAX_ENDPOINT,
                        data=payload,
                        headers=headers,
                        timeout=httpx.Timeout(timeout),
                    )
                else:
                    resp = client.post(AJAX_ENDPOINT, data=payload, headers=headers, timeout=timeout)
            except Exception as e:
                logging.debug("RentSFNow page %d request failed: %s", page, e)
                break

            if resp.status_code == 400:
                logging.debug("RentSFNow 400 on page %d; payload=%s", page, payload)
                resp.raise_for_status()

            resp.raise_for_status()
            html = resp.text
            page_units = parse_listings(html, base_url=referer)

            if not page_units:
                logging.debug("RentSFNow page %d returned 0 units; stopping.", page)
                break

            # Apply ZIP filter here (after parse, before dedupe) if provided
            if allowed_zips:
                page_units = [
                    u for u in page_units
                    if _neighborhood_matches_zip(u.neighborhood, allowed_zips)
                ]

            if not page_units:
                logging.debug("RentSFNow page %d: all units filtered out by ZIPs %s", page, sorted(allowed_zips))
                page += 1
                if delay:
                    import time as _t
                    _t.sleep(delay)
                continue

            new_count = 0
            for u in page_units:
                if u.source_url not in seen_urls:
                    seen_urls.add(u.source_url)
                    all_units.append(u)
                    new_count += 1

            logging.debug(
                "RentSFNow page %d: %d units (%d new, %d total) after ZIP filter",
                page, len(page_units), new_count, len(all_units)
            )

            if new_count == 0:
                logging.debug("No new units on page %d; stopping.", page)
                break

            page += 1
            if delay:
                import time as _t
                _t.sleep(delay)

        return all_units
    finally:
        if close_session:
            try:
                client.close()
            except Exception:
                pass


def _infer_zip(address: Optional[str], neighborhood: Optional[str]) -> Optional[str]:
    if address:
        m = _ZIP_RE.search(address)
        if m:
            return m.group(0)
    if neighborhood:
        zset = _NEIGHBORHOOD_ZIP_MAP.get(neighborhood.strip().lower())
        if zset:
            return sorted(zset)[0]
    return None


def parse_listings(html: str, *, base_url: str = DEFAULT_URL) -> List[Unit]:
    """
    Parse the HTML fragment returned by wpas_ajax_load.
    Keeps original selector + adds fallbacks.
    """
    soup = BeautifulSoup(html, "lxml")
    containers = soup.select("div.searchDetailSpacing")
    if not containers:
        # Try alternative modern card selectors
        containers = soup.select("div.property-card, article.property, div.listing-card")

    units: List[Unit] = []
    for c in containers:
        anchor = c.find("a", href=True)
        href = anchor["href"] if anchor else None
        source_url = urljoin(base_url, href) if href else base_url

        address_el = c.select_one("h2, h2.address, h2.property-address")
        address = address_el.get_text(strip=True) if address_el else None

        hood_el = c.select_one("h3, .neighborhood, .property-neighborhood")
        neighborhood = hood_el.get_text(strip=True) if hood_el else None

        info_blocks = c.select("p.apartment-info, .details, .property-meta, ul li")
        bedrooms, bathrooms, rent = _extract_unit_details(info_blocks)

        if not address and not href:
            continue

        zip_code = _infer_zip(address, neighborhood)  # NEW

        units.append(
            Unit(
                address=address,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                rent=rent,
                neighborhood=neighborhood,
                source_url=source_url,
                zip_code=zip_code,  # NEW
            )
        )
    return units


def apply_filter_params(
    url: str,
    *,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[Iterable[str]] = None,
    min_rent: Optional[int] = None,
    **_: Any,
) -> str:
    """
    Embed filters into the URL so build_payload picks them up.

    Writes a consolidated price=min,max param (preferred by the live site).
      min_rent (optional) + max_rent -> price=min,max
      If only max_rent -> price=0,max
      If only min_rent -> price=min,
    """
    absolute = _ensure_absolute(url)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query, keep_blank_values=True)
    changed = False

    # Derive existing price range if present
    existing_price = query.get("price", [""])[-1]
    existing_min = None
    existing_max = None
    if existing_price:
        if "," in existing_price:
            lo, hi = existing_price.split(",", 1)
            if lo.strip().isdigit():
                existing_min = int(lo.strip())
            if hi.strip().isdigit():
                existing_max = int(hi.strip())
        elif existing_price.isdigit():
            existing_max = int(existing_price)

    # Bedrooms
    if min_bedrooms is not None:
        query["bedrooms"] = [str(int(math.ceil(min_bedrooms)))]
        changed = True

    # Neighborhood (take first)
    if neighborhoods:
        first = next((n.strip() for n in neighborhoods if n and n.strip()), "")
        if first:
            query["neighborhood"] = [first]
            changed = True

    # Price range handling
    use_min = min_rent if min_rent is not None else existing_min
    use_max = max_rent if max_rent is not None else existing_max

    if max_rent is not None or min_rent is not None:
        # Compose new price param
        if use_min is None and use_max is not None:
            price_val = f"0,{use_max}"
        elif use_min is not None and use_max is not None:
            price_val = f"{use_min},{use_max}"
        elif use_min is not None and use_max is None:
            price_val = f"{use_min},"
        else:
            price_val = ""  # unlikely
        query["price"] = [price_val]
        # Remove legacy keys if present
        for legacy in ("min_price", "max_price", "minprice", "maxprice"):
            query.pop(legacy, None)
        changed = True

    if not changed:
        return absolute

    new_q = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_q))


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

