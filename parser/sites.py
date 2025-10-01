"""Utilities for parsing site configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .models import Site


def load_sites_yaml(path: str | Path) -> List[Site]:
    """Load site definitions from a YAML file located at *path*."""

    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    return parse_sites_yaml(text)


def parse_sites_yaml(text: str) -> List[Site]:
    """Parse *text* containing a ``sites`` YAML list into :class:`Site` objects."""

    entries = _parse_site_entries(text)
    sites: List[Site] = []
    seen_slugs: set[str] = set()

    for entry in entries:
        slug = _normalise_value(entry.get("slug"))
        url = _normalise_value(entry.get("url"))
        if not slug or not url:
            raise ValueError("Each site entry must include 'slug' and 'url' values.")
        if slug in seen_slugs:
            raise ValueError(f"Duplicate site slug detected: {slug}")
        seen_slugs.add(slug)
        sites.append(Site(slug=slug, url=url))

    return sites


def _parse_site_entries(text: str) -> List[Dict[str, str]]:
    in_sites = False
    current: Dict[str, str] | None = None
    entries: List[Dict[str, str]] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if not in_sites:
            if stripped.startswith("sites"):
                in_sites = True
            continue

        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            remainder = stripped[2:].strip()
            if remainder:
                key, value = _split_key_value(remainder)
                current[key] = value
            continue

        if stripped == "-":
            current = {}
            entries.append(current)
            continue

        if current is None or ":" not in stripped:
            continue

        key, value = _split_key_value(stripped)
        current[key] = value

    return entries


def _split_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"Expected key/value pair in line: {text!r}")
    key, value = text.split(":", 1)
    key = key.strip()
    value = _parse_scalar(value.strip())
    return key, value


def _parse_scalar(value: str) -> str:
    value = _strip_inline_comment(value)
    value = value.strip()

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]

    return value.strip()


def _strip_inline_comment(value: str) -> str:
    result: List[str] = []
    in_single = False
    in_double = False

    for char in value:
        if char == "'" and not in_double:
            in_single = not in_single
            result.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            result.append(char)
            continue
        if char == "#" and not in_single and not in_double:
            break
        result.append(char)

    return "".join(result)


def _normalise_value(value: str | None) -> str:
    return value.strip() if value is not None else ""


__all__ = ["load_sites_yaml", "parse_sites_yaml"]
