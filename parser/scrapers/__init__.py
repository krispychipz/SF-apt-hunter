"""Scraper registry mapping site slugs to callable fetchers."""

from __future__ import annotations

from typing import Callable, Dict, List

from parser.models import Site, Unit

ScraperFunc = Callable[[str], List[Unit]]


def _load_default_scrapers() -> Dict[str, ScraperFunc]:
    registry: Dict[str, ScraperFunc] = {}
    missing: List[str] = []
    '''
    try:
        from .amsires_scraper import fetch_units as amsires_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "amsires_scraper dependency"))
    else:
        registry["amsires"] = amsires_fetch

    try:
        from .anchorealty_scraper import fetch_units as anchorealty_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "anchorealty_scraper dependency"))
    else:
        registry["anchorealty"] = anchorealty_fetch

    try:
        from .relisto_scraper import fetch_units as relisto_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "relisto_scraper dependency"))
    else:
        registry["relisto"] = relisto_fetch

    try:
        from .chandlerproperties_scraper import fetch_units as chandler_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "chandlerproperties_scraper dependency"))
    else:
        registry["chandlerproperties"] = chandler_fetch
    '''
    try:
        from .structure_scraper import fetch_units as structure_fetch
    except ModuleNotFoundError as exc:
        missing.append(getattr(exc, "name", "structure_scraper dependency"))
    else:
        registry["structure"] = structure_fetch
    '''
    try:
        from .rentbt_scraper import fetch_units as rentbt_fetch
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        missing.append(getattr(exc, "name", "rentbt_scraper dependency"))
    else:
        registry["rentbt"] = rentbt_fetch
    '''
    if not registry and missing:
        details = ", ".join(sorted(set(filter(None, missing))))
        raise RuntimeError(
            f"No scrapers available because required dependencies are missing: {details}"
        )

    return registry


def available_scrapers() -> Dict[str, ScraperFunc]:
    """Return a copy of the built-in scraper registry."""

    return _load_default_scrapers().copy()


def available_sites() -> List[Site]:
    """Return :class:`Site` definitions inferred from bundled scrapers."""

    registry = _load_default_scrapers()
    sites: List[Site] = []
    for slug, scraper in registry.items():
        default_url = getattr(scraper, "default_url", "")
        if default_url == "":  
            raise RuntimeError(
                f"Scraper for site '{slug}' is missing a 'default_url' attribute"
            )
        sites.append(Site(slug=slug, url=default_url))
    return sites


__all__ = ["ScraperFunc", "available_scrapers", "available_sites"]
