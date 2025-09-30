"""Core extractor that drives fetching and parsing."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import httpx
import yaml
from jsonpath_ng.ext import parse as jsonpath_parse
from selectolax.parser import HTMLParser
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from .normalize import (
    infer_neighborhood,
    parse_baths,
    parse_beds,
    parse_date,
    parse_rent,
    parse_sqft,
)
from .util import stable_hash
from .validate import Listing

logger = logging.getLogger(__name__)

CONFIG_DIR = Path("config/sites")
USER_AGENT = "SF-Apt-Hunter/1.0"
_ROBOTS_CACHE: dict[str, robotparser.RobotFileParser | None] = {}


@dataclass
class RateLimiter:
    interval: float
    last_called: float = 0.0

    def wait(self) -> None:
        now = time.time()
        if self.last_called and self.interval > 0:
            elapsed = now - self.last_called
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
        self.last_called = time.time()


def load_config(site: str) -> dict:
    path = CONFIG_DIR / f"{site}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found for site '{site}'")
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    data = yaml.safe_load(raw) or {}
    data.setdefault("name", site)
    return data


def ensure_robots_allowed(client: httpx.Client, url: str) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parser = _ROBOTS_CACHE.get(base)
    if parser is None:
        robots_url = urljoin(base, "/robots.txt")
        parser = robotparser.RobotFileParser()
        try:
            resp = client.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10.0)
            if resp.status_code < 400:
                parser.parse(resp.text.splitlines())
            else:
                parser = None
        except httpx.HTTPError:
            parser = None
        _ROBOTS_CACHE[base] = parser
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch_seed(client: httpx.Client, url: str, rate_limiter: RateLimiter | None = None) -> httpx.Response:
    if rate_limiter:
        rate_limiter.wait()
    if not ensure_robots_allowed(client, url):
        raise PermissionError(f"Robots disallows fetching {url}")
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20.0)
    resp.raise_for_status()
    return resp


def strategy_jsonld(config: dict, seed_url: str, html: str) -> list[dict]:
    results: list[dict] = []
    jsonld_conf = config.get("jsonld") or {}
    unit_paths = jsonld_conf.get("unit_paths", [])
    field_map = jsonld_conf.get("field_map", {})
    if not unit_paths:
        return results
    parser = HTMLParser(html)
    scripts = parser.css("script[type='application/ld+json']")
    docs: list[Any] = []
    for script in scripts:
        try:
            docs.append(json.loads(script.text()))
        except json.JSONDecodeError:
            continue
    for doc in docs:
        for path_expr in unit_paths:
            try:
                expr = jsonpath_parse(path_expr)
            except Exception as exc:  # pragma: no cover
                logger.warning("Invalid jsonpath %s: %s", path_expr, exc)
                continue
            for match in expr.find(doc):
                unit = match.value
                row = {field: extract_jsonpath_value(unit, field_map, field) for field in field_map}
                row.update(unit if isinstance(unit, dict) else {})
                results.append(row)
    return results


def extract_jsonpath_value(doc: Any, field_map: dict, field: str) -> Any:
    expression = field_map.get(field)
    if not expression:
        return None
    try:
        expr = jsonpath_parse(expression)
    except Exception as exc:  # pragma: no cover
        logger.warning("Invalid jsonpath for %s: %s", field, exc)
        return None
    matches = expr.find(doc)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].value
    return [m.value for m in matches]


def strategy_xhr(config: dict, seed_url: str, client: httpx.Client) -> list[dict]:
    xhr_conf = config.get("xhr") or {}
    endpoints: list[str] = xhr_conf.get("endpoints", [])
    field_map = xhr_conf.get("field_map", {})
    unit_paths = xhr_conf.get("unit_paths", [])
    if not endpoints:
        return []
    results: list[dict] = []
    for endpoint in endpoints:
        target = urljoin(seed_url, endpoint)
        try:
            if not ensure_robots_allowed(client, target):
                logger.info("Robots disallows %s", target)
                continue
            resp = client.get(target, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=20.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("XHR fetch failed for %s: %s", target, exc)
            continue
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("XHR payload at %s not JSON", target)
            continue
        docs = [payload]
        for path_expr in unit_paths or ["$"]:
            try:
                expr = jsonpath_parse(path_expr)
            except Exception as exc:
                logger.warning("Invalid jsonpath %s: %s", path_expr, exc)
                continue
            for match in expr.find(payload):
                node = match.value
                row = {field: extract_jsonpath_value(node, field_map, field) for field in field_map}
                if isinstance(node, dict):
                    row.update({k: v for k, v in node.items() if k not in row})
                results.append(row)
    return results


def strategy_dom(config: dict, html: str) -> list[dict]:
    dom_conf = config.get("dom") or {}
    selector = dom_conf.get("list_selector")
    field_selectors = dom_conf.get("field_selectors", {})
    regex_helpers = dom_conf.get("regex_helpers", {})
    if not selector:
        return []
    parser = HTMLParser(html)
    results: list[dict] = []
    for node in parser.css(selector):
        record: dict[str, Any] = {}
        for field, sel in field_selectors.items():
            if not sel:
                continue
            attr_name = None
            selector = sel
            if "::attr(" in sel:
                selector, attr_part = sel.split("::attr(", 1)
                attr_name = attr_part.rstrip(")")
            subnode = node.css_first(selector.strip()) if selector else node
            if not subnode:
                continue
            if attr_name:
                text = subnode.attributes.get(attr_name)
            else:
                text = subnode.text(strip=True)
            if text is None:
                continue
            if field in regex_helpers:
                pattern = regex_helpers[field]
                if pattern:
                    match = re.search(pattern, str(text))
                    if match:
                        text = match.group(1)
            record[field] = text
        results.append(record)
    return results


def normalize_row(site: str, raw: dict, seed_url: str, config: dict, scraped_at: float) -> dict:
    hints = config.get("hints", {})
    rent_field = raw.get("rent") or raw.get("price")
    rent_min = raw.get("rent_min")
    rent_max = raw.get("rent_max")
    if rent_field is not None:
        parsed_min, parsed_max = parse_rent(str(rent_field))
        rent_min = parsed_min or rent_min
        rent_max = parsed_max or rent_max
    if rent_min is not None and not isinstance(rent_min, int):
        rent_min, _ = parse_rent(str(rent_min))
    if rent_max is not None and not isinstance(rent_max, int):
        _, rent_max = parse_rent(str(rent_max))
    beds = parse_beds(str(raw.get("beds"))) if raw.get("beds") is not None else None
    baths = parse_baths(str(raw.get("baths"))) if raw.get("baths") is not None else None
    sqft = parse_sqft(str(raw.get("sqft"))) if raw.get("sqft") is not None else None
    available_source = raw.get("available") or raw.get("available_date")
    available = parse_date(str(available_source)) if available_source else None

    row = {
        "source": site,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(scraped_at)),
        "title": raw.get("title") or raw.get("name"),
        "address": raw.get("address"),
        "unit": raw.get("unit") or raw.get("unit_number"),
        "neighborhood": raw.get("neighborhood") or infer_neighborhood(seed_url, hints),
        "beds": beds,
        "baths": baths,
        "sqft": sqft,
        "rent_min": rent_min or raw.get("rent_min"),
        "rent_max": rent_max or raw.get("rent_max"),
        "available_date": available,
        "url": raw.get("url") or seed_url,
    }
    return row


def validate_row(row: dict) -> Listing | None:
    try:
        listing = Listing.parse_obj(row)
    except Exception as exc:
        logger.debug("Row failed validation: %s", exc)
        return None
    return listing


def extract_site(site: str, client: httpx.Client | None = None) -> list[Listing]:
    config = load_config(site)
    seeds: list[str] = config.get("seeds", [])
    strategy_order: list[str] = config.get("strategy_order", ["jsonld", "xhr", "dom"])
    rate_limit_seconds = config.get("rate_limit", 1.0)
    rate_limiter = RateLimiter(interval=float(rate_limit_seconds)) if rate_limit_seconds else None

    close_client = False
    if client is None:
        client = httpx.Client(follow_redirects=True)
        close_client = True

    listings: list[Listing] = []
    scraped_at = time.time()
    try:
        for seed in seeds:
            logger.info("Fetching seed %s", seed)
            try:
                response = fetch_seed(client, seed, rate_limiter)
            except RetryError as exc:
                logger.error("Failed to fetch %s after retries: %s", seed, exc)
                continue
            html = response.text
            raw_units: list[dict] = []
            for strategy in strategy_order:
                if strategy == "jsonld":
                    units = strategy_jsonld(config, seed, html)
                elif strategy == "xhr":
                    units = strategy_xhr(config, seed, client)
                elif strategy == "dom":
                    units = strategy_dom(config, html)
                else:
                    logger.warning("Unknown strategy %s", strategy)
                    continue
                if units:
                    logger.info("%s: %s yielded %d units", site, strategy, len(units))
                    raw_units.extend(units)
                    break
            if not raw_units:
                logger.warning("%s: No units parsed for %s", site, seed)
                continue
            seen: dict[str, Listing] = {}
            for raw in raw_units:
                normalized = normalize_row(site, raw, seed, config, scraped_at)
                listing = validate_row(normalized)
                if not listing:
                    continue
                key = stable_hash([listing.url, listing.unit or "", listing.address or ""])
                seen[key] = listing
            listings.extend(seen.values())
    finally:
        if close_client:
            client.close()
    return listings


__all__ = [
    "load_config",
    "fetch_seed",
    "strategy_jsonld",
    "strategy_xhr",
    "strategy_dom",
    "normalize_row",
    "validate_row",
    "extract_site",
]
