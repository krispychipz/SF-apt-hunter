"""High-level workflow helpers for orchestrating scraper runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import logging

from .models import Site, Unit
from .scrapers import ScraperFunc, available_scrapers


@dataclass(slots=True)
class SiteProcessingResult:
    """Encapsulates the outcome of running a scraper for a single site."""

    site: Site
    units: List[Unit]
    error: Optional[Exception] = None


@dataclass(slots=True)
class WorkflowResult:
    """Aggregated results for a batch extraction run."""

    site_results: List[SiteProcessingResult]

    @classmethod
    def single_batch(cls, units: Iterable[Unit]) -> "WorkflowResult":
        """Create a result wrapper for ad-hoc unit lists (e.g., single HTML input)."""

        dummy_site = Site(slug="ad-hoc", url="")
        result = SiteProcessingResult(dummy_site, list(units), error=None)
        return cls([result])

    @property
    def units(self) -> List[Unit]:
        """Return all unique units aggregated across successful site results."""

        unique: List[Unit] = []
        seen: set[tuple] = set()
        for site_result in self.site_results:
            if site_result.error is not None:
                continue
            for unit in site_result.units:
                identity = unit.identity()
                if identity in seen:
                    continue
                seen.add(identity)
                unique.append(unit)
        return unique

    @property
    def errors(self) -> List[SiteProcessingResult]:
        """Return site results that encountered an error during processing."""

        return [result for result in self.site_results if result.error is not None]


def collect_units_from_sites(
    sites: Sequence[Site],
    *,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[set[str]] = None,
    scrapers: Optional[Dict[str, ScraperFunc]] = None,
) -> WorkflowResult:
    """Execute registered scrapers for each site in *sites* and apply filters."""

    registry = _prepare_registry(scrapers)
    site_results: List[SiteProcessingResult] = []

    for site in sites:
        key = _normalise_slug(site.slug)
        scraper = registry.get(key)
        if scraper is None:
            error = RuntimeError(f"No scraper registered for site slug '{site.slug}'")
            site_results.append(SiteProcessingResult(site=site, units=[], error=error))
            continue

        try:
            if site.url:
                units = scraper(site.url)
            else:
                units = scraper()
            filtered_units = filter_units(
                units,
                min_bedrooms=min_bedrooms,
                max_rent=max_rent,
                neighborhoods=neighborhoods,
            )
            site_results.append(
                SiteProcessingResult(site=site, units=filtered_units, error=None)
            )
        except Exception as exc:  # pragma: no cover - defensive logging branch
            logging.debug("Error while processing site %s", site.slug, exc_info=True)
            site_results.append(SiteProcessingResult(site=site, units=[], error=exc))

    return WorkflowResult(site_results)


def filter_units(
    units: Iterable[Unit],
    *,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[set[str]] = None,
) -> List[Unit]:
    """Filter *units* according to user-provided criteria."""

    normalized_neighborhoods = (
        {name.strip().lower() for name in neighborhoods if name.strip()}
        if neighborhoods
        else None
    )

    filtered: List[Unit] = []
    for unit in units:
        if min_bedrooms is not None:
            if unit.bedrooms is None or unit.bedrooms < min_bedrooms:
                continue

        if max_rent is not None:
            if unit.rent is None or unit.rent > max_rent:
                continue

        if normalized_neighborhoods is not None:
            if (
                unit.neighborhood is None
                or unit.neighborhood.strip().lower() not in normalized_neighborhoods
            ):
                continue

        filtered.append(unit)

    return filtered


def _prepare_registry(
    scrapers: Optional[Dict[str, ScraperFunc]] = None,
) -> Dict[str, ScraperFunc]:
    registry = scrapers or available_scrapers()
    return {_normalise_slug(slug): scraper for slug, scraper in registry.items()}


def _normalise_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "-")


__all__ = [
    "SiteProcessingResult",
    "WorkflowResult",
    "collect_units_from_sites",
    "filter_units",
]
