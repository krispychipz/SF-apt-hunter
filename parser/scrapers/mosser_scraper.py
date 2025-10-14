"""Scraper for Mosser Living San Francisco listings."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin
import html  # NEW

import requests
from bs4 import BeautifulSoup, Tag

from parser.heuristics import clean_neighborhood, money_to_int, parse_bathrooms, parse_bedrooms
from parser.models import Unit

DEFAULT_URL = "https://www.mosserliving.com/san-francisco-apartments/all/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_LOGGER = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:
    sync_playwright = None  # type: ignore


def _extract_json_data(tag: Tag) -> Optional[dict[str, Any]]:
    script = tag.find("script", attrs={"type": "application/ld+json"})
    text = _script_text(script) if script else None
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _LOGGER.debug("Failed to parse JSON-LD block", exc_info=True)
        return None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
        return None
    if isinstance(data, dict):
        return data
    return None


def _script_text(script: Tag) -> Optional[str]:
    if script is None:
        return None
    if script.string and script.string.strip():
        return script.string.strip()
    text = script.get_text()
    text = text.strip()
    return text or None


def _decode_data_properties_attr(raw: str) -> Optional[list[dict[str, Any]]]:
    """Decode the data-properties attribute (HTML-escaped JSON array)."""
    if not raw:
        return None
    try:
        unescaped = html.unescape(raw)
    except Exception:
        unescaped = raw
    unescaped = unescaped.strip()
    # Some themes may wrap in quotes
    if (unescaped.startswith("'") and unescaped.endswith("'")) or (unescaped.startswith('"') and unescaped.endswith('"')):
        unescaped = unescaped[1:-1].strip()
    try:
        data = json.loads(unescaped)
    except Exception:
        _LOGGER.debug("Failed json.loads on data-properties (len=%d)", len(unescaped))
        return None
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return None


def _decode_json_attr(raw: str) -> Optional[Any]:
    if not raw:
        return None
    try:
        txt = html.unescape(raw).strip()
        # Strip wrapping quotes if present
        if (txt.startswith('"') and txt.endswith('"')) or (txt.startswith("'") and txt.endswith("'")):
            txt = txt[1:-1].strip()
        return json.loads(txt)
    except Exception:
        return None


_FLOORPLAN_FALLBACK_SELECTORS = [
    "div.rentpress-shortcode-floorplan-card",
    "div.rentpress-floorplan-card",
    "div.rentpress-floorplan-wrapper",
    "div.floorplan-card",
    "article.rentpress-floorplan-card",
]


@dataclass
class _RenderedDetail:
    html: str
    ldjson_payloads: List[str]

def _extract_basic_fields(text: str) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Best-effort extraction of beds/baths/rent from inline card text."""

    if not text:
        return None, None, None

    beds = parse_bedrooms(text)
    baths = parse_bathrooms(text)
    rent = money_to_int(text)

    return beds, baths, rent


def _extract_embedded_properties(html_text: str) -> list[dict[str, Any]]:
    """Return list of property dicts from the #rentpress-app data-properties attribute."""
    soup = BeautifulSoup(html_text, "lxml")
    host = soup.find("div", id="rentpress-app")
    if not host:
        return []
    raw = host.get("data-properties")
    if not raw:
        return []
    decoded = _decode_data_properties_attr(raw)
    if not decoded:
        return []
    _LOGGER.debug("Decoded %d embedded properties from data-properties", len(decoded))
    return decoded


def _properties_to_tuples(props: list[dict[str, Any]]) -> list[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
    """Convert property dicts to tuples: (detail_url, address, neighborhood, zip_code)."""
    out: list[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []
    for p in props:
        link = p.get("property_post_link") or p.get("property_website") or p.get("property_availability_url")
        if not isinstance(link, str):
            continue
        address = p.get("property_address")
        if not isinstance(address, str):
            address = None
        neighborhood = p.get("property_primary_neighborhood_post_name") or p.get("property_city")
        if isinstance(neighborhood, str):
            neighborhood = clean_neighborhood(neighborhood)
        else:
            neighborhood = None
        zip_code = p.get("property_zip")
        if not isinstance(zip_code, str):
            zip_code = None
        out.append((link, address, neighborhood, zip_code))
    return out


def _parse_property_card(
    card: Tag, *, base_url: str
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    anchor = card.find("a", href=True)
    if not anchor:
        return None
    property_url = urljoin(base_url, anchor["href"])

    data = _extract_json_data(card)
    address: Optional[str] = None
    neighborhood: Optional[str] = None

    subtitle = anchor.select_one(".v-card__subtitle")
    if (subtitle):
        text = subtitle.get_text(" ", strip=True)
        cleaned = clean_neighborhood(text)
        neighborhood = cleaned or None

    if data:
        address_info = data.get("address")
        if isinstance(address_info, dict):
            address = (
                address_info.get("streetAddress")
                or address_info.get("addressLocality")
                or address_info.get("addressRegion")
            )
            if neighborhood is None:
                locality = address_info.get("addressLocality")
                region = address_info.get("addressRegion")
                parts = [p for p in (locality, region) if p]
                if parts:
                    neighborhood = clean_neighborhood(", ".join(parts)) or None

        if not neighborhood:
            name = data.get("name")
            if isinstance(name, str):
                neighborhood = clean_neighborhood(name) or None

    if not address:
        title = anchor.select_one(".rentpress-property-card-title")
        if title:
            address = title.get_text(strip=True) or None

    return property_url, address, neighborhood


def parse_property_list(html: str, *, base_url: str = DEFAULT_URL) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Return property detail URLs with associated metadata."""

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.property-card-wrapper")

    results: List[Tuple[str, Optional[str], Optional[str]]] = []
    for card in cards:
        parsed = _parse_property_card(card, base_url=base_url)
        if parsed is None:
            continue
        results.append(parsed)

    return results


def _extract_floorplan_details(tag: Tag) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    info_el = tag.select_one(".v-card__subtitle")
    info_text = info_el.get_text(" ", strip=True) if info_el else ""

    bedrooms = parse_bedrooms(info_text)
    bathrooms = parse_bathrooms(info_text)

    rent_text = tag.get_text(" ", strip=True)
    rent = money_to_int(rent_text)

    return bedrooms, bathrooms, rent


def _parse_floorplan_ldjson(card: Tag) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    script = card.find("script", attrs={"type": "application/ld+json"})
    text = _script_text(script) if script else None
    if not text:
        return None, None, None
    try:
        data = json.loads(text)
    except Exception:
        return None, None, None
    # Schema can be Product with about: FloorPlan
    bedrooms = bathrooms = rent = None
    if isinstance(data, dict):
        about = data.get("about") if isinstance(data.get("about"), dict) else None
        if about:
            b = about.get("numberOfBedrooms")
            if isinstance(b, (int, float, str)):
                try: bedrooms = float(str(b).strip())
                except Exception: pass
            bt = about.get("numberOfBathroomsTotal") or about.get("numberOfBathrooms")
            if isinstance(bt, (int, float, str)):
                try: bathrooms = float(str(bt).strip())
                except Exception: pass
        offers = data.get("offers") if isinstance(data.get("offers"), dict) else None
        if offers:
            # Prefer lowPrice/highPrice; fall back to price
            price_fields = [offers.get("lowPrice"), offers.get("highPrice"), offers.get("price")]
            for pf in price_fields:
                if pf in (None, "", "null"): continue
                try:
                    val = int(str(pf).replace("$", "").replace(",", "").strip())
                    # Ignore suspiciously small numbers (< 500) to avoid street numbers
                    if val >= 500:
                        rent = val
                        break
                except Exception:
                    continue
    return bedrooms, bathrooms, rent


# --- Robust LD+JSON floorplan harvesting ------------------------------------

def _iter_json_objects(parsed: Any):
    if isinstance(parsed, dict):
        yield parsed
        for v in parsed.values():
            yield from _iter_json_objects(v)
    elif isinstance(parsed, list):
        for item in parsed:
            yield from _iter_json_objects(item)


def _extract_value_as_float(val: Any) -> Optional[float]:
    if val in (None, "", "null"): return None
    try:
        return float(str(val).strip())
    except Exception:
        return None


def _extract_price_int(*vals: Any) -> Optional[int]:
    for v in vals:
        if v in (None, "", "null"): continue
        try:
            candidate = int(str(v).replace("$", "").replace(",", "").strip())
            # Heuristic: ignore clearly non-rent small numbers (< 500)
            if candidate >= 500:
                return candidate
        except Exception:
            continue
    return None


def _merge_unit_details(existing: Unit, candidate: Unit) -> Unit:
    return Unit(
        address=existing.address or candidate.address,
        bedrooms=candidate.bedrooms if candidate.bedrooms is not None else existing.bedrooms,
        bathrooms=candidate.bathrooms if candidate.bathrooms is not None else existing.bathrooms,
        rent=candidate.rent if candidate.rent is not None else existing.rent,
        neighborhood=existing.neighborhood or candidate.neighborhood,
        source_url=existing.source_url,
        zip_code=getattr(existing, "zip_code", None),
    )


def _extract_floorplans_from_ldjson(
    soup: BeautifulSoup,
    *,
    property_url: str,
    address: Optional[str],
    neighborhood: Optional[str],
    extra_payloads: Iterable[str] = (),
) -> List[Unit]:
    payloads: list[str] = []
    seen: set[str] = set()
    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = _script_text(sc)
        if not text or text in seen:
            continue
        seen.add(text)
        payloads.append(text)
    for raw in extra_payloads:
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        payloads.append(cleaned)

    unit_by_source: Dict[str, Unit] = {}
    for raw in payloads:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        for obj in _iter_json_objects(parsed):
            if not isinstance(obj, dict):
                continue
            atype = obj.get("@type") or obj.get("type")
            if atype == "Product" and isinstance(obj.get("about"), dict):
                fp = obj["about"]
                if fp.get("@type") == "FloorPlan":
                    beds = _extract_value_as_float(fp.get("numberOfBedrooms"))
                    baths = _extract_value_as_float(
                        fp.get("numberOfBathroomsTotal") or fp.get("numberOfBathrooms")
                    )
                    offers = obj.get("offers") if isinstance(obj.get("offers"), dict) else None
                    rent = None
                    if offers:
                        rent = _extract_price_int(
                            offers.get("lowPrice"), offers.get("highPrice"), offers.get("price")
                        )
                    link = fp.get("url") or obj.get("url") or property_url
                    source_url = urljoin(property_url, link) if isinstance(link, str) else property_url
                    candidate = Unit(
                        address=address,
                        bedrooms=beds,
                        bathrooms=baths,
                        rent=rent,
                        neighborhood=neighborhood,
                        source_url=source_url,
                    )
                    existing = unit_by_source.get(source_url)
                    unit_by_source[source_url] = (
                        _merge_unit_details(existing, candidate) if existing else candidate
                    )
                    _LOGGER.debug(
                        "LD+JSON fp: beds=%s baths=%s rent=%s url=%s",
                        beds,
                        baths,
                        rent,
                        source_url,
                    )
            elif atype == "FloorPlan":
                beds = _extract_value_as_float(obj.get("numberOfBedrooms") or obj.get("bedrooms"))
                baths = _extract_value_as_float(
                    obj.get("numberOfBathroomsTotal")
                    or obj.get("numberOfBathrooms")
                    or obj.get("bathrooms")
                )
                rent = None
                link = obj.get("url") or property_url
                source_url = urljoin(property_url, link) if isinstance(link, str) else property_url
                candidate = Unit(
                    address=address,
                    bedrooms=beds,
                    bathrooms=baths,
                    rent=rent,
                    neighborhood=neighborhood,
                    source_url=source_url,
                )
                existing = unit_by_source.get(source_url)
                unit_by_source[source_url] = (
                    _merge_unit_details(existing, candidate) if existing else candidate
                )
    units = list(unit_by_source.values())
    if units:
        _LOGGER.debug("Mosser LD+JSON extracted %d floorplan units from %s", len(units), property_url)
    return units


def _debug_ldjson_presence(html: str, extra_payloads: Iterable[str] = ()):  # pragma: no cover - diagnostics
    """Lightweight diagnostic to count ld+json and occurrences of key fields."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    sample = 0
    has_bed_kw = 0
    for sc in scripts:
        text = _script_text(sc)
        if not text:
            continue
        sample += 1
        lowered = text.lower()
        if "numberofbedrooms" in lowered or "floorplan" in lowered:
            has_bed_kw += 1
    for payload in extra_payloads:
        if not isinstance(payload, str):
            continue
        cleaned = payload.strip()
        if not cleaned:
            continue
        sample += 1
        lowered = cleaned.lower()
        if "numberofbedrooms" in lowered or "floorplan" in lowered:
            has_bed_kw += 1
    _LOGGER.debug(
        "Mosser detail diagnostics: %d ld+json scripts (%d with floorplan hints)",
        sample,
        has_bed_kw,
    )


def _parse_card_inline_ldjson(card: Tag) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Parse the single <script type=application/ld+json> inside a floorplan card."""
    script = card.find("script", attrs={"type": "application/ld+json"})
    text = _script_text(script) if script else None
    if not text:
        return None, None, None
    try:
        data = json.loads(text)
    except Exception:
        return None, None, None
    # Reuse logic from _parse_floorplan_ldjson but simplified
    if isinstance(data, dict):
        if data.get("@type") == "Product" and isinstance(data.get("about"), dict):
            about = data["about"]
            beds = _extract_value_as_float(about.get("numberOfBedrooms"))
            baths = _extract_value_as_float(about.get("numberOfBathroomsTotal") or about.get("numberOfBathrooms"))
            offers = data.get("offers") if isinstance(data.get("offers"), dict) else None
            rent = None
            if offers:
                rent = _extract_price_int(offers.get("lowPrice"), offers.get("highPrice"), offers.get("price"))
            return beds, baths, rent
        if data.get("@type") == "FloorPlan":
            beds = _extract_value_as_float(data.get("numberOfBedrooms") or data.get("bedrooms"))
            baths = _extract_value_as_float(data.get("numberOfBathroomsTotal") or data.get("numberOfBathrooms") or data.get("bathrooms"))
            return beds, baths, None
    return None, None, None


# --- JS rendering helper (add before parse_property_page) ---
def _render_detail_with_playwright(
    detail_url: str, timeout: int, wait_selector: str
) -> Optional[_RenderedDetail]:
    if sync_playwright is None:
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = None
            try:
                context = browser.new_context(user_agent=HEADERS.get("User-Agent"))
                page = context.new_page()
                page.set_default_timeout(timeout * 1000)
                page.goto(detail_url, wait_until="domcontentloaded")
                for _ in range(6):
                    count = page.evaluate(
                        """() => Array.from(document.querySelectorAll("script[type='application/ld+json']"))
                        .filter(s => /numberOfBedrooms|FloorPlan/i.test((s.textContent || ''))).length"""
                    )
                    if isinstance(count, (int, float)) and count > 0:
                        break
                    page.evaluate("""() => window.scrollTo(0, document.body.scrollHeight)""")
                    try:
                        page.wait_for_selector(wait_selector, timeout=1000)
                        break
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                html = page.content()
                raw_payloads = page.evaluate(
                    """() => Array.from(document.querySelectorAll("script[type='application/ld+json']"))
                    .map(s => s.textContent || '').filter(Boolean)"""
                )
            finally:
                try:
                    if context is not None:
                        context.close()
                finally:
                    browser.close()
            payloads: list[str] = []
            if isinstance(raw_payloads, list):
                for item in raw_payloads:
                    if isinstance(item, str):
                        cleaned = item.strip()
                        if cleaned:
                            payloads.append(cleaned)
            return _RenderedDetail(html=html, ldjson_payloads=payloads)
    except Exception as exc:
        _LOGGER.debug("Playwright render failed %s: %s", detail_url, exc)
        return None


def parse_property_page(
    html: str,
    *,
    property_url: str,
    address: Optional[str],
    neighborhood: Optional[str],
    allow_js: bool = True,
    timeout: int = 20,
) -> List[Unit]:
    """Parse an individual property page into Unit objects.

    Steps:
      1. Scan LD+JSON for floorplans.
      2. data-floorplans attribute (RentPress) if present.
      3. Floorplan cards + per-card LD+JSON.
      4. JS render fallback (Playwright) if still empty and allowed.
      5. Final property-level heuristic.
    """
    def _extract_all(html_text: str, *, ldjson_payloads: Iterable[str] = ()) -> List[Unit]:
        soup = BeautifulSoup(html_text, "lxml")

        # (1) Page-level LD+JSON
        ldjson_units = _extract_floorplans_from_ldjson(
            soup,
            property_url=property_url,
            address=address,
            neighborhood=neighborhood,
            extra_payloads=ldjson_payloads,
        )
        if ldjson_units:
            return ldjson_units

        # (2) data-floorplans attribute
        host = soup.find("div", id="rentpress-app")
        if host:
            raw_fp = host.get("data-floorplans") or host.get("data-floorplan") or host.get("data-fp")
            if raw_fp:
                decoded = _decode_json_attr(raw_fp)
                units: List[Unit] = []
                if isinstance(decoded, list):
                    for fp in decoded:
                        if not isinstance(fp, dict):
                            continue
                        beds = _extract_value_as_float(fp.get("bedrooms") or fp.get("beds"))
                        baths = _extract_value_as_float(fp.get("bathrooms") or fp.get("baths"))
                        rent = _extract_price_int(fp.get("rent"), fp.get("min_rent"), fp.get("lowest_rent"), fp.get("price"))
                        link = fp.get("permalink") or fp.get("url") or property_url
                        src = urljoin(property_url, link) if isinstance(link, str) else property_url
                        units.append(Unit(address=address, bedrooms=beds, bathrooms=baths, rent=rent, neighborhood=neighborhood, source_url=src))
                if units:
                    return units

        # (3) Card-based
        cards = soup.select("div.rentpress-shortcode-floorplan-card, div.rentpress-floorplan-card, article.rentpress-floorplan-card")
        units: List[Unit] = []
        for card in cards:
            b, ba, r = _parse_card_inline_ldjson(card)
            if not any([b, ba, r]):
                # Try wider function if inline ldjson absent or empty
                b2, ba2, r2 = _parse_floorplan_ldjson(card)
                b = b or b2
                ba = ba or ba2
                r = r or r2
            if not any([b, ba, r]):
                # Fallback to basic text inference
                tb, tba, tr = _extract_basic_fields(card.get_text(" ", strip=True))
                b = b or tb
                ba = ba or tba
                r = r or tr
            a = card.find("a", href=True)
            if not a:
                a = card.find_parent("a", href=True)
            src = urljoin(property_url, a["href"]) if a else property_url
            units.append(Unit(address=address, bedrooms=b, bathrooms=ba, rent=(r if (r is None or r >= 500) else None), neighborhood=neighborhood, source_url=src))
        if units:
            return units

        return []

    # First pass (static HTML)
    _debug_ldjson_presence(html)
    units = _extract_all(html)
    if units:
        return units

    # (4) JS render fallback
    if allow_js and sync_playwright is not None:
        rendered = _render_detail_with_playwright(
            property_url,
            timeout,
            "div.rentpress-shortcode-floorplan-card script[type='application/ld+json']",
        )
        if rendered:
            _debug_ldjson_presence(rendered.html, rendered.ldjson_payloads)
            units = _extract_all(rendered.html, ldjson_payloads=rendered.ldjson_payloads)
            if units:
                _LOGGER.debug(
                    "Mosser: JS render produced %d floorplan units for %s",
                    len(units),
                    property_url,
                )
                return units

    # (5) Final property-level heuristic single unit
    gb, gbath, grent = _extract_basic_fields(html)
    return [
        Unit(
            address=address,
            bedrooms=gb,
            bathrooms=gbath,
            rent=(grent if (grent is None or grent >= 500) else None),
            neighborhood=neighborhood,
            source_url=property_url,
        )
    ]


def fetch_units(
    url: str = DEFAULT_URL,
    *,
    timeout: int = 20,
    session: Optional[Any] = None,
    use_embedded: bool = True,
    js_detail_fallback: bool = True,  # NEW
) -> List[Unit]:
    """Fetch Mosser Living listings and return them as :class:`Unit` objects.

    Order:
      1. (Optional) Try embedded data-properties JSON for property metadata.
      2. Fallback to static DOM card parsing.
      3. Parse each property detail page for floorplans.
    """
    client: Any
    close_session = False

    if session is not None:
        client = session
    else:
        client = requests.Session()
        close_session = True
        if hasattr(client, "headers"):
            try:
                client.headers.update(HEADERS)
            except Exception:  # pragma: no cover
                pass

    try:
        resp = client.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        html_text = resp.text

        property_tuples: list[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []

        embedded_props: list[dict[str, Any]] = []
        if use_embedded:
            embedded_props = _extract_embedded_properties(html_text)
            if embedded_props:
                property_tuples = _properties_to_tuples(embedded_props)

        if not property_tuples:
            # Fallback to legacy card parsing (no zip_code from this path)
            legacy = parse_property_list(html_text, base_url=url)
            property_tuples = [(u, a, n, None) for (u, a, n) in legacy]

        if not property_tuples:
            _LOGGER.debug("Mosser: 0 properties found (embedded=%s)", bool(embedded_props))
            return []

        units: List[Unit] = []
        seen_detail_urls: set[str] = set()

        for property_url, address, neighborhood, zip_code in property_tuples:
            # Normalize URL
            if not property_url.startswith("http"):
                property_url = urljoin(url, property_url)

            if property_url in seen_detail_urls:
                continue
            seen_detail_urls.add(property_url)

            try:
                detail = client.get(property_url, headers=HEADERS, timeout=timeout)
                detail.raise_for_status()
            except requests.RequestException as exc:  # pragma: no cover
                _LOGGER.debug("Skip property detail %s: %s", property_url, exc)
                continue

            detail_units = parse_property_page(
                detail.text,
                property_url=property_url,
                address=address,
                neighborhood=neighborhood,
                allow_js=js_detail_fallback,
                timeout=timeout,
            )

            # Inject zip_code if we decoded one (Unit may or may not have that field)
            for du in detail_units:
                if zip_code and getattr(du, "zip_code", None) in (None, ""):
                    try:
                        setattr(du, "zip_code", zip_code)
                    except Exception:
                        pass

            units.extend(detail_units)

        _LOGGER.debug(
            "Mosser: %d properties -> %d units (embedded=%s)",
            len(property_tuples),
            len(units),
            bool(embedded_props),
        )
        return units
    finally:
        if close_session:
            try:
                client.close()
            except Exception:
                pass


fetch_units.default_url = DEFAULT_URL  # type: ignore[attr-defined]


def debug_capture_floorplan_network(detail_url: str, timeout: int = 20):
    if sync_playwright is None:
        _LOGGER.debug("Playwright not available for network capture.")
        return
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS.get("User-Agent"))
        hits = []
        def _log_response(resp):
            try:
                ct = resp.headers.get("content-type","").lower()
                url = resp.url
                if "json" in ct or any(k in url for k in ("floorplan","rentpress","rentcafe")):
                    body = resp.text()
                    low = body.lower()
                    if any(k in low for k in ("floorplan","bed","bath")):
                        hits.append((url, body[:400]))
            except Exception:
                pass
        context.on("response", _log_response)
        page = context.new_page()
        page.set_default_timeout(timeout * 1000)
        page.goto(detail_url, wait_until="networkidle")
        for u, snippet in hits:
            _LOGGER.debug("Floorplan candidate URL: %s\nSnippet: %s", u, snippet)
        context.close()
        browser.close()
