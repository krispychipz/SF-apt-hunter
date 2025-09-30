"""Normalization helpers for listing values."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

BED_RE = re.compile(r"(?P<value>\d+(?:\.5)?)\s*bed", re.IGNORECASE)
BATH_RE = re.compile(r"(?P<value>\d+(?:\.5)?)\s*bath", re.IGNORECASE)
PRICE_RE = re.compile(r"\$\s*([0-9,]+)")
SQFT_RE = re.compile(r"([0-9,]+)\s*(?:sq\.?\s*ft\.?|square\s*feet)", re.IGNORECASE)
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"]


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.debug("Unable to parse float from %s", value)
        return None


def parse_beds(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = BED_RE.search(text)
    if match:
        return parse_float(match.group("value"))
    try:
        return float(text)
    except ValueError:
        return None


def parse_baths(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = BATH_RE.search(text)
    if match:
        return parse_float(match.group("value"))
    try:
        return float(text)
    except ValueError:
        return None


def parse_rent(text: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    prices = [int(p.replace(",", "")) for p in PRICE_RE.findall(text)]
    if not prices:
        try:
            value = int(float(text))
            return value, value
        except ValueError:
            return None, None
    if len(prices) == 1:
        return prices[0], prices[0]
    return min(prices), max(prices)


def parse_sqft(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = SQFT_RE.search(text)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # try today/now keywords
    lowered = text.lower()
    if lowered in {"now", "immediately", "today"}:
        return datetime.utcnow().date().isoformat()
    return None


def infer_neighborhood(seed: str, hints: Optional[dict]) -> Optional[str]:
    if not hints:
        return None
    by_seed = hints.get("neighborhood_from_seed", {})
    for prefix, name in by_seed.items():
        if seed.startswith(prefix):
            return name
    return hints.get("default_neighborhood")
