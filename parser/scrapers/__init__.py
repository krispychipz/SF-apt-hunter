"""Scraper registry mapping site slugs to callable fetchers."""

from __future__ import annotations

from typing import Callable, Dict, List

from parser.models import Unit

ScraperFunc = Callable[[str], List[Unit]]


def _load_default_scrapers() -> Dict[str, ScraperFunc]:
    registry: Dict[str, ScraperFunc] = {}
    missing: List[str] = []

    try:
        from .amsires_scraper import fetch_units as amsires_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "amsires_scraper dependency"))
    else:
        registry["amsires"] = amsires_fetch

    try:
        from .relisto_scraper import fetch_units as relisto_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "relisto_scraper dependency"))
    else:
        registry["relisto"] = relisto_fetch

    if not registry and missing:
        details = ", ".join(sorted(set(filter(None, missing))))
        raise RuntimeError(
            f"No scrapers available because required dependencies are missing: {details}"
        )

    return registry


def available_scrapers() -> Dict[str, ScraperFunc]:
    """Return a copy of the built-in scraper registry."""

    return _load_default_scrapers().copy()


__all__ = ["ScraperFunc", "available_scrapers"]
