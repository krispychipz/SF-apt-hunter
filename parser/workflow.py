"""High-level workflow helpers for orchestrating scraper runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import logging
import re

from .models import Site, Unit
from .scrapers import ScraperFunc, available_scrapers


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SiteProcessingResult:
    """Encapsulates the outcome of running a scraper for a single site."""

    site: Site
    units: List[Unit]  # filtered units
    error: Optional[Exception] = None
    total_extracted: int = 0  # add this field


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
    zip_codes: Optional[set[str]] = None,
    scrapers: Optional[Dict[str, ScraperFunc]] = None,
) -> WorkflowResult:
    """Execute registered scrapers for each site in *sites* and apply filters."""

    registry = _prepare_registry(scrapers)
    #print("Registered scrapers:", registry.keys())
    #print("Sites to process:", [site.slug for site in sites])
    site_results: List[SiteProcessingResult] = []

    for site in sites:
        key = _normalise_slug(site.slug)
        scraper = registry.get(key)
        if scraper is None:
            error = RuntimeError(f"No scraper registered for site slug '{site.slug}'")
            logger.error("%s", error)
            site_results.append(SiteProcessingResult(site=site, units=[], error=error))
            continue

        try:
            logger.debug("Running scraper for site '%s' (%s)", site.slug, site.url)
            if site.url:
                scraper_url = site.url
                apply_filters = getattr(scraper, "apply_filter_params", None)
                if callable(apply_filters):
                    try:
                        scraper_url = apply_filters(
                            scraper_url,
                            min_bedrooms=min_bedrooms,
                            max_rent=max_rent,
                            neighborhoods=neighborhoods,
                            zip_codes=zip_codes,
                        )
                    except Exception:  # pragma: no cover - defensive
                        logger.exception(
                            "Failed to apply filters to scraper URL for site '%s'", site.slug
                        )
                extracted_units = scraper(scraper_url)
            else:
                extracted_units = scraper()
            filtered_units = filter_units(
                extracted_units,
                min_bedrooms=min_bedrooms,
                max_rent=max_rent,
                neighborhoods=neighborhoods,
                zip_codes=zip_codes,
            )
            logger.debug(
                "Scraper '%s' returned %d unit(s); %d unit(s) remain after filtering",
                site.slug,
                len(extracted_units),
                len(filtered_units),
            )
            site_results.append(
                SiteProcessingResult(
                    site=site,
                    units=filtered_units,
                    error=None,
                    total_extracted=len(extracted_units),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive logging branch
            logger.exception("Error while processing site '%s'", site.slug)
            site_results.append(SiteProcessingResult(site=site, units=[], error=exc, total_extracted=0))

    return WorkflowResult(site_results)


def filter_units(
    units: Iterable[Unit],
    *,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[set[str]] = None,
    zip_codes: Optional[set[str]] = None,
) -> List[Unit]:
    """Filter *units* according to user-provided criteria."""

    normalized_neighborhoods = (
        {name.strip().lower() for name in neighborhoods if name.strip()}
        if neighborhoods
        else None
    )
    normalized_zip_codes = (
        _normalise_zip_codes(zip_codes)
        if zip_codes
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

        if normalized_zip_codes:
            address_zips = _extract_zip_codes(unit.address or "")
            if not address_zips or address_zips.isdisjoint(normalized_zip_codes):
                continue

        filtered.append(unit)

    return filtered


def _prepare_registry(
    scrapers: Optional[Dict[str, ScraperFunc]] = None,
) -> Dict[str, ScraperFunc]:
    if scrapers is None:
        registry = available_scrapers()
    else:
        registry = scrapers
    return {_normalise_slug(slug): scraper for slug, scraper in registry.items()}


def _normalise_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "-")


__all__ = [
    "SiteProcessingResult",
    "WorkflowResult",
    "collect_units_from_sites",
    "filter_units",
]


_ZIP_CODE_PATTERN = re.compile(r"\b(\d{5})(?:-(\d{4}))?\b")


def _extract_zip_codes(text: str) -> set[str]:
    matches: set[str] = set()
    for match in _ZIP_CODE_PATTERN.finditer(text):
        base = match.group(1)
        extension = match.group(2)
        matches.add(base)
        if extension:
            matches.add(f"{base}-{extension}")
    return matches


def _normalise_zip_codes(zip_codes: set[str]) -> set[str]:
    normalized: set[str] = set()
    for value in zip_codes:
        if not value:
            continue
        extracted = _extract_zip_codes(value)
        if extracted:
            normalized.update(extracted)
        else:
            cleaned = value.strip()
            if cleaned:
                normalized.add(cleaned)
    return normalized
