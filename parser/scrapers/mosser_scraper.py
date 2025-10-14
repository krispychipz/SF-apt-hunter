"""Scraper for Mosser Living San Francisco listings."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, List, Optional, Tuple, cast
from urllib.parse import urljoin, urlsplit, urlunsplit
import html  # NEW
from concurrent.futures import ThreadPoolExecutor, as_completed  # NEW

import requests
from bs4 import BeautifulSoup

from parser.heuristics import clean_neighborhood
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

# Selectors for floorplan card containers on detail pages rendered by RentPress/Vuetify
CARD_CONTAINER_SELECTORS: list[str] = [
    "#rentpress-app .v-card",
    "#rentpress-app .v-list-item",
    ".floorplan-card",
    "[data-floorplan-card]",
    ".fp-card",
]

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except Exception:
    sync_playwright = None  # type: ignore


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


def _extract_embedded_properties(html_text: str) -> list[dict[str, Any]]:
    """Extract embedded RentPress property objects from the listing page.
    Looks for a #rentpress-app (or any) node with a data-properties attribute
    containing an HTML-escaped JSON array of property dicts.
    """
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return []

    host = soup.find(id="rentpress-app")
    candidates: list[str] = []
    if host is not None:
        for key in ("data-properties", "data-props", "data-listings"):
            val = host.get(key) if hasattr(host, "get") else None
            if isinstance(val, str) and val.strip():
                candidates.append(val)
    if not candidates:
        any_node = soup.find(attrs={"data-properties": True})
        if any_node is not None and hasattr(any_node, "get"):
            val = any_node.get("data-properties")
            if isinstance(val, str) and val.strip():
                candidates.append(val)

    for raw in candidates:
        decoded = _decode_data_properties_attr(raw)
        if decoded:
            return decoded
    return []


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
            if candidate >= 500:
                return candidate
        except Exception:
            continue
    return None


def _iter_ldjson_objects(parsed: Any):
    """Yield all dict objects from nested ld+json structures."""
    if isinstance(parsed, dict):
        yield parsed
        for v in parsed.values():
            yield from _iter_ldjson_objects(v)
    elif isinstance(parsed, list):
        for item in parsed:
            yield from _iter_ldjson_objects(item)


def _units_from_ldjson_payloads(
    payloads: Iterable[str],
    *,
    property_url: str,
    address: Optional[str],
    neighborhood: Optional[str],
) -> List[Unit]:
    """Consolidated JSON-LD interpretation for FloorPlan/Product(about=FloorPlan)."""
    out: List[Unit] = []
    seen: set[tuple] = set()
    ok_payloads = 0
    bad_payloads = 0
    obj_count = 0
    type_seen: dict[str, int] = {}

    for raw in payloads:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
            ok_payloads += 1
        except Exception as e:
            bad_payloads += 1
            try:
                _LOGGER.debug("Mosser: ld+json parse error on %s (len=%d): %s", property_url, len(raw), e)
            except Exception:
                pass
            continue

        for obj in _iter_ldjson_objects(parsed):
            if not isinstance(obj, dict):
                continue
            obj_count += 1

            atype = obj.get("@type") or obj.get("type")
            if isinstance(atype, list):
                # Prefer specific known types
                atype = next((t for t in atype if t in ("Product", "FloorPlan")), atype[0] if atype else None)
            if isinstance(atype, str):
                type_seen[atype] = type_seen.get(atype, 0) + 1

            beds = baths = None
            rent = None

            if atype == "Product":
                about = obj.get("about") if isinstance(obj.get("about"), dict) else None
                if about and about.get("@type") == "FloorPlan":
                    beds = _extract_value_as_float(about.get("numberOfBedrooms"))
                    baths = _extract_value_as_float(
                        about.get("numberOfBathroomsTotal") or about.get("numberOfBathrooms")
                    )
                # Offers can be dict or list and may nest priceSpecification
                offers = obj.get("offers")
                offer_candidates: list[Any] = []
                if isinstance(offers, dict):
                    offer_candidates.extend([
                        offers.get("lowPrice"), offers.get("highPrice"), offers.get("price")
                    ])
                    ps = offers.get("priceSpecification")
                    if isinstance(ps, dict):
                        offer_candidates.extend([ps.get("minPrice"), ps.get("maxPrice"), ps.get("price")])
                elif isinstance(offers, list):
                    for off in offers:
                        if not isinstance(off, dict):
                            continue
                        offer_candidates.extend([off.get("lowPrice"), off.get("highPrice"), off.get("price")])
                        ps = off.get("priceSpecification")
                        if isinstance(ps, dict):
                            offer_candidates.extend([ps.get("minPrice"), ps.get("maxPrice"), ps.get("price")])
                rent = _extract_price_int(*offer_candidates)

            elif atype == "FloorPlan":
                beds = _extract_value_as_float(obj.get("numberOfBedrooms") or obj.get("bedrooms"))
                baths = _extract_value_as_float(
                    obj.get("numberOfBathroomsTotal") or obj.get("numberOfBathrooms") or obj.get("bathrooms")
                )
                # Some FloorPlan nodes might also include offers/pricing
                offers = obj.get("offers")
                offer_candidates: list[Any] = []
                if isinstance(offers, dict):
                    offer_candidates.extend([
                        offers.get("lowPrice"), offers.get("highPrice"), offers.get("price")
                    ])
                    ps = offers.get("priceSpecification")
                    if isinstance(ps, dict):
                        offer_candidates.extend([ps.get("minPrice"), ps.get("maxPrice"), ps.get("price")])
                elif isinstance(offers, list):
                    for off in offers:
                        if not isinstance(off, dict):
                            continue
                        offer_candidates.extend([off.get("lowPrice"), off.get("highPrice"), off.get("price")])
                        ps = off.get("priceSpecification")
                        if isinstance(ps, dict):
                            offer_candidates.extend([ps.get("minPrice"), ps.get("maxPrice"), ps.get("price")])
                rent = _extract_price_int(*offer_candidates)
            else:
                try:
                    _LOGGER.debug("Mosser: ignoring ld+json @type=%s on %s", atype, property_url)
                except Exception:
                    pass

            if any([beds, baths, rent]):
                sig = (
                    round(beds, 2) if isinstance(beds, float) else beds,
                    round(baths, 2) if isinstance(baths, float) else baths,
                    rent,
                )
                if sig in seen:
                    continue
                seen.add(sig)
                out.append(
                    Unit(
                        address=address,
                        bedrooms=beds,
                        bathrooms=baths,
                        rent=rent,
                        neighborhood=neighborhood,
                        source_url=property_url,
                    )
                )
    try:
        _LOGGER.debug(
            "Mosser: ld+json summary for %s -> payloads ok=%d, failed=%d, objects=%d, types=%s, units=%d",
            property_url,
            ok_payloads,
            bad_payloads,
            obj_count,
            dict(sorted(type_seen.items())),
            len(out),
        )
    except Exception:
        pass
    return out


def _properties_to_tuples(props: list[dict[str, Any]]) -> list[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
    """Convert property dicts to tuples: (detail_url, address, neighborhood, zip_code)."""
    out: list[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []
    for p in props:
        link = p.get("property_post_link") or p.get("property_website") or p.get("property_availability_url")
        if not isinstance(link, str):
            continue
        # Removed restrictive path filter to allow all property links
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


def _extract_units_with_playwright(
    detail_url: str,
    *,
    address: Optional[str],
    neighborhood: Optional[str],
    timeout: int,
    page: Optional[Any] = None,
) -> List[Unit]:
    """Render detail with Playwright, collect ld+json payloads from floorplan cards, and parse in Python."""
    if sync_playwright is None:
        return []
    created = False
    browser = context = None
    pw_ctrl = None
    try:
        if page is None:
            from playwright.sync_api import sync_playwright as _sp  # type: ignore
            pw_ctrl = _sp().start()
            browser = pw_ctrl.chromium.launch(headless=True)
            context = browser.new_context(user_agent=HEADERS.get("User-Agent"))
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)
            created = True

        page.goto(detail_url, wait_until="networkidle")

        # Passive readiness waits (no clicks)
        for sel, wait_ms in (("#rentpress-app, .v-application", 3000), ("script[type='application/ld+json']", 3000)):
            try:
                page.wait_for_selector(sel, timeout=wait_ms)
            except Exception:
                pass

        # Passive scroll loop to trigger lazy render
        stable_iters = 0
        last_counts = (-1, -1)
        for _ in range(20):
            try:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            page.wait_for_timeout(500)
            try:
                counts = page.evaluate(
                    """
                    () => {
                        const host = document.querySelector('#rentpress-app') || document;
                        const scripts = Array.from(host.querySelectorAll("script[type='application/ld+json']"));
                        return [scripts.length, scripts.length];
                    }
                    """
                )
            except Exception:
                counts = [0, 0]

            try:
                card_count, ld_count = int(counts[0]), int(counts[1])
            except Exception:
                card_count, ld_count = 0, 0

            if (card_count, ld_count) == last_counts:
                stable_iters += 1
            else:
                stable_iters = 0
                last_counts = (card_count, ld_count)

            if ld_count > 0 and stable_iters >= 2:
                break

        # Collect payloads from floorplan containers first; fallback to whole app/document
        try:
            selectors_js = ", ".join([json.dumps(s) for s in CARD_CONTAINER_SELECTORS])
            payloads = page.evaluate(
                f"""
                () => {{
                  const sels = [{selectors_js}];
                  const out = [];
                  const cards = Array.from(document.querySelectorAll(sels.join(',')));
                  cards.forEach(card => {{
                    card.querySelectorAll("script[type='application/ld+json']").forEach(sc => {{
                      const t = (sc.textContent || "").trim();
                      if (t) out.push(t);
                    }});
                  }});
                  if (out.length === 0) {{
                    const host = document.querySelector('#rentpress-app') || document;
                    host.querySelectorAll("script[type='application/ld+json']").forEach(sc => {{
                      const t = (sc.textContent || "").trim();
                      if (t) out.push(t);
                    }});
                  }}
                  return out;
                }}
                """
            )
        except Exception:
            payloads = []

        if not isinstance(payloads, list):
            payloads = []

        try:
            _LOGGER.debug("Mosser: %s -> collected %d ld+json payload(s)%s",
                          detail_url,
                          len(payloads),
                          ("; first snippet=" + (payloads[0][:120].replace("\n", " ") + "...") if payloads else ""))
        except Exception:
            pass

        if not payloads:
            _LOGGER.debug("Mosser: no ld+json payloads found for %s", detail_url)

        units = _units_from_ldjson_payloads(
            payloads,
            property_url=detail_url,
            address=address,
            neighborhood=neighborhood,
        )
        return [u for u in units if any([u.bedrooms, u.bathrooms, u.rent])]
    except Exception as exc:
        _LOGGER.debug("Playwright extraction failed %s: %s", detail_url, exc)
        return []
    finally:
        if created:
            try:
                if context is not None:
                    context.close()
            finally:
                try:
                    if browser is not None:
                        browser.close()
                finally:
                    try:
                        if pw_ctrl is not None:
                            pw_ctrl.stop()
                    except Exception:
                        pass


def _normalize_trailing(url: str) -> List[str]:
    base = url.rstrip("/")
    return [base, base + "/"]


def fetch_units(
    url: str = DEFAULT_URL,
    *,
    timeout: int = 20,
    session: Optional[Any] = None,
    use_embedded: bool = True,
    max_properties: int = 200,
    filter_bedrooms: Optional[int] = None,
    concurrency: int = 4,  # NEW
) -> List[Unit]:
    """Fetch Mosser Living listings and return them as Unit objects.

    Discovery:
      1. Read embedded data-properties JSON for property metadata (address, neighborhood, zip).
      2. For each property, render the detail page with Playwright and parse per-card JSON-LD.
    """
    # Hard requirement: Playwright must be available for unit extraction
    if sync_playwright is None:
      _LOGGER.debug("Mosser: Playwright not available; returning no units.")
      return []

    url = _build_filtered_list_url(url, filter_bedrooms)
    _LOGGER.debug("Mosser: listing URL after filter_bedrooms=%s -> %s (concurrency=%d)", filter_bedrooms, url, concurrency)

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
            _LOGGER.debug("Mosser: 0 properties found (embedded=%s)", bool(embedded_props))
            return []

        units: List[Unit] = []
        seen_detail_urls: set[str] = set()

        def _run_one(prop_url: str, addr: Optional[str], hood: Optional[str], zc: Optional[str]) -> List[Unit]:
            # Each worker creates and tears down its own Playwright instance
            try:
                us = _extract_units_with_playwright(
                    prop_url,
                    address=addr,
                    neighborhood=hood,
                    timeout=timeout,
                    page=None,  # let the helper create its own browser/context/page
                )
                for u in us:
                    try:
                        u.source_url = prop_url
                    except Exception:
                        pass
                if zc:
                    for du in us:
                        if getattr(du, "zip_code", None) in (None, ""):
                            try:
                                setattr(du, "zip_code", zc)
                            except Exception:
                                pass
                return us
            except Exception as exc:
                _LOGGER.debug("Playwright worker failed for %s: %s", prop_url, exc)
                return []

        futures = []
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as executor:
            for idx, (property_url, address, neighborhood, zip_code) in enumerate(property_tuples, 1):
                if idx > max_properties:
                    _LOGGER.debug("Mosser: reached max_properties=%d, stopping.", max_properties)
                    break
                if not property_url.startswith("http"):
                    property_url = urljoin(url, property_url)
                if property_url in seen_detail_urls:
                    continue
                seen_detail_urls.add(property_url)

                futures.append(executor.submit(_run_one, property_url, address, neighborhood, zip_code))

            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception as exc:
                    _LOGGER.debug("Mosser: worker raised exception: %s", exc)
                    res = []
                if res:
                    units.extend(res)

        _LOGGER.debug(
            "Mosser: %d properties -> %d units (embedded=%s)",
            len(seen_detail_urls),
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


def _build_filtered_list_url(list_url: str, bedrooms: Optional[int]) -> str:
    """
    Return a Mosser listing URL filtered by bedroom count:
      - 0 -> /san-francisco-apartments/studio/
      - N >= 1 -> /san-francisco-apartments/{N}-bed/
    If the base path doesn't contain '/san-francisco-apartments/', returns list_url unchanged.
    """
    if bedrooms is None:
        return list_url
    try:
        parts = urlsplit(list_url)
        segment = "/san-francisco-apartments/"
        if segment not in parts.path:
            return list_url
        root_idx = parts.path.find(segment) + len(segment)
        root_path = parts.path[:root_idx]
        if bedrooms == 0:
            slug = "studio/"
        elif isinstance(bedrooms, int) and bedrooms > 0:
            slug = f"{bedrooms}-bed/"
        else:
            return list_url
        new_path = root_path + slug
        return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))
    except Exception:
        return list_url
