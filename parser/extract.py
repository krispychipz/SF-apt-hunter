"""Core HTML extraction logic for apartment listings."""

from __future__ import annotations

import logging
from typing import Callable, Iterable, List, Optional, Sequence, Set, Tuple

try:  # pragma: no cover - exercised indirectly in environments with bs4
    from bs4 import BeautifulSoup, Tag
except ModuleNotFoundError:  # pragma: no cover - fallback used in tests
    from ._fallback_bs4 import BeautifulSoup, Tag

from .heuristics import (
    clean_neighborhood,
    looks_like_address,
    money_to_int,
    parse_bathrooms,
    parse_bedrooms,
)
from .models import Unit

_LOGGER = logging.getLogger(__name__)

_PRICE_TOKENS = ("$", "rent", "per month")
_BED_TOKENS = ("bed", "bd", "br")
_BATH_TOKENS = ("bath", "ba")
_NEIGHBORHOOD_TOKENS = ("neighborhood", "hood", "district", "area", "breadcrumb")


ParserFunc = Callable[[str], Optional[float]]


def extract_units(html: str | bytes, source_url: str) -> List[Unit]:
    """Extract unit records from an HTML document."""

    html_text = html.decode("utf-8", errors="ignore") if isinstance(html, bytes) else html
    soup = BeautifulSoup(html_text, "lxml")

    containers = _find_listing_containers(soup)
    _LOGGER.info("Identified %d candidate containers", len(containers))

    units: List[Unit] = []
    seen: Set[Tuple[Optional[str], Optional[float], Optional[float], Optional[int]]] = set()

    for container in containers:
        unit = _extract_from_container(container, source_url)
        key = unit.identity()
        if key in seen:
            _LOGGER.debug("Skipping duplicate unit: %s", key)
            continue
        if not any((unit.address, unit.rent, unit.bedrooms, unit.bathrooms)):
            snippet = container.get_text(" ", strip=True)[:80]
            _LOGGER.debug("Skipping empty unit in container starting '%s'", snippet)
            continue
        seen.add(key)
        units.append(unit)

    return units


def _find_listing_containers(soup: BeautifulSoup) -> List[Tag]:
    """Return a list of probable listing containers within *soup*."""

    candidates: List[Tag] = []

    for element in soup.find_all(True):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        lower = text.lower()
        if not _contains_token(lower, _PRICE_TOKENS):
            continue
        if not (_contains_token(lower, _BED_TOKENS) or _contains_token(lower, _BATH_TOKENS)):
            continue
        candidates.append(element)

    candidates.sort(key=_element_depth, reverse=True)
    selected: List[Tag] = []
    for element in candidates:
        if any(sel in element.parents for sel in selected):
            continue
        selected.append(element)

    selected.sort(key=_document_position)
    return selected


def _extract_from_container(container: Tag, source_url: str) -> Unit:
    address = _find_address(container)
    bedrooms = _find_first_value(container, parse_bedrooms)
    bathrooms = _find_first_value(container, parse_bathrooms)
    rent = _find_rent(container)
    neighborhood = _find_neighborhood(container)

    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=neighborhood,
        source_url=source_url,
    )


def _find_address(container: Tag) -> Optional[str]:
    """Locate an address within *container*."""

    address_tags: List[Tag] = []
    address_tags.extend(container.find_all("address"))

    for tag in container.find_all(True):
        attr_block = _collect_attr_text(tag)
        if any(keyword in attr_block for keyword in ("address", "addr", "location")):
            address_tags.append(tag)

    for tag in address_tags:
        text = tag.get_text(" ", strip=True)
        if text:
            return text

    for line in _iter_text_lines(container):
        if looks_like_address(line):
            return line
    return None


def _find_first_value(container: Tag, parser: ParserFunc) -> Optional[float]:
    for text in _iter_text_lines(container):
        value = parser(text)
        if value is not None:
            return value
    return None


def _find_rent(container: Tag) -> Optional[int]:
    for text in _iter_text_lines(container):
        value = money_to_int(text)
        if value is not None:
            return value
    return None


def _find_neighborhood(container: Tag) -> Optional[str]:
    for tag in container.find_all(True):
        attr_block = _collect_attr_text(tag)
        if any(token in attr_block for token in _NEIGHBORHOOD_TOKENS):
            text = tag.get_text(" ", strip=True)
            cleaned = clean_neighborhood(text)
            if cleaned:
                return cleaned

    for line in _iter_text_lines(container):
        lower = line.lower()
        if any(token in lower for token in _NEIGHBORHOOD_TOKENS):
            cleaned = clean_neighborhood(line)
            if cleaned:
                return cleaned
    return None


def _iter_text_lines(container: Tag) -> Iterable[str]:
    for text in container.stripped_strings:
        cleaned = " ".join(text.split())
        if cleaned:
            yield cleaned


def _collect_attr_text(tag: Tag) -> str:
    tokens: List[str] = []

    class_attr = tag.get("class")
    if isinstance(class_attr, str):
        tokens.append(class_attr.lower())
    elif isinstance(class_attr, (list, tuple, set)):
        tokens.extend(str(item).lower() for item in class_attr)

    id_attr = tag.get("id")
    if id_attr:
        tokens.append(str(id_attr).lower())

    role_attr = tag.get("role")
    if role_attr:
        tokens.append(str(role_attr).lower())

    aria_label = tag.get("aria-label")
    if aria_label:
        tokens.append(str(aria_label).lower())

    return " ".join(tokens)


def _contains_token(text: str, tokens: Sequence[str]) -> bool:
    return any(token in text for token in tokens)


def _element_depth(element: Tag) -> int:
    depth = 0
    for _ in element.parents:
        depth += 1
    return depth


def _document_position(element: Tag) -> Tuple[int, int]:
    sourceline = getattr(element, "sourceline", 0)
    sourcepos = getattr(element, "sourcepos", 0)
    return (sourceline, sourcepos)
