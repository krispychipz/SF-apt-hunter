"""Text processing heuristics for apartment extraction."""

from __future__ import annotations

import logging
import re
from typing import Optional

_LOGGER = logging.getLogger(__name__)

_MONEY_PATTERN = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
    flags=re.IGNORECASE,
)
_RANGE_PATTERN = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*[\u2013\-]\s*\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?",
    flags=re.IGNORECASE,
)
_NUMBER_TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_BED_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:bed|beds|bedroom|bedrooms|br|brs|bd|bds|bdr|bdrm)\b",
    flags=re.IGNORECASE,
)
_BATH_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:bath|baths|bathroom|bathrooms|ba|bth)\b",
    flags=re.IGNORECASE,
)
_ADDRESS_PATTERN = re.compile(
    r"\b\d+\s+[A-Za-z0-9.'\- ]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Way|Ct|Court|Ln|Lane|Ter|Terrace|Pl|Place|Pkwy|Parkway|Cir|Circle)\b",
    flags=re.IGNORECASE,
)
_UNIT_MARKERS = ("#", "Unit", "Apt", "Apartment", "Suite")


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def money_to_int(text: str) -> Optional[int]:
    """Extract an integer amount of USD from *text*.

    Returns the lower bound for ranges and ``None`` for non-price strings.
    """

    if not text:
        return None

    lowered = text.lower()
    if "call" in lowered and "price" in lowered:
        return None

    text = text.replace("\xa0", " ")
    range_match = _RANGE_PATTERN.search(text)
    if range_match:
        value = range_match.group(1)
        _LOGGER.debug("Parsed rent range '%s' -> %s", text, value)
        return int(value.replace(",", ""))

    match = _MONEY_PATTERN.search(text)
    if not match:
        return None

    value = match.group(1).replace(",", "")
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_bedrooms(text: str) -> Optional[float]:
    """Parse the bedroom count from *text* if present."""

    if not text:
        return None

    lowered = text.lower()
    if "studio" in lowered:
        return 0.0
    if "loft" in lowered:
        return None

    normalised = re.sub(r"[\-/]", " ", lowered)
    match = _BED_PATTERN.search(normalised)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_bathrooms(text: str) -> Optional[float]:
    """Parse the bathroom count from *text* if present."""

    if not text:
        return None

    lowered = text.lower()
    normalised = re.sub(r"[\-/]", " ", lowered)
    match = _BATH_PATTERN.search(normalised)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def looks_like_address(text: str) -> bool:
    """Return True if *text* appears to be a street address."""

    if not text:
        return False

    cleaned = _normalise_text(text)
    if not cleaned:
        return False

    if _ADDRESS_PATTERN.search(cleaned):
        return True

    for marker in _UNIT_MARKERS:
        if marker.lower() in cleaned.lower():
            digits = _NUMBER_TOKEN_PATTERN.findall(cleaned)
            if digits:
                return True
    return False


def clean_neighborhood(text: str) -> str:
    """Return a compact neighbourhood name derived from *text*."""

    cleaned = _normalise_text(text)
    if not cleaned:
        return ""

    parts = [part.strip() for part in re.split(r"[,/|\u2022]", cleaned) if part.strip()]
    if parts:
        candidate = parts[0]
    else:
        candidate = cleaned

    candidate = re.sub(r"\b(San\s+Francisco|CA|California)\b", "", candidate, flags=re.IGNORECASE)
    candidate = _normalise_text(candidate)

    return candidate or cleaned
