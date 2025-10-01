"""High-level workflow helpers for fetching and extracting listings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, TYPE_CHECKING

import logging

try:  # pragma: no cover - requests might be unavailable in some environments
    import requests  # type: ignore
except ImportError:  # pragma: no cover - handled gracefully at runtime
    requests = None  # type: ignore

if TYPE_CHECKING:  # pragma: no cover - typing helper only
    import requests as _requests

from .extract import extract_units
from .models import Site, Unit

FetchFunction = Callable[[Site], tuple[str, Optional[Path]]]


@dataclass(slots=True)
class SiteProcessingResult:
    """Encapsulates the outcome of fetching and extracting a single site."""

    site: Site
    units: List[Unit]
    html_path: Optional[Path]
    error: Optional[Exception] = None


@dataclass(slots=True)
class WorkflowResult:
    """Aggregated results for a batch extraction run."""

    site_results: List[SiteProcessingResult]

    @classmethod
    def single_batch(cls, units: Iterable[Unit]) -> "WorkflowResult":
        """Create a result wrapper for ad-hoc unit lists (e.g., single HTML input)."""

        dummy_site = Site(slug="ad-hoc", url="")
        result = SiteProcessingResult(dummy_site, list(units), html_path=None)
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
    session: Optional["_requests.Session"] = None,
    headers: Optional[dict[str, str]] = None,
    download_dir: Optional[Path] = None,
    min_bedrooms: Optional[float] = None,
    max_rent: Optional[int] = None,
    neighborhoods: Optional[set[str]] = None,
    fetch_html: Optional[FetchFunction] = None,
) -> WorkflowResult:
    """Fetch, extract, and filter units for every site in *sites*.

    Parameters are designed so callers (including tests) can inject custom
    networking behaviour by supplying *session* or *fetch_html*.
    """

    if fetch_html is None:
        if requests is None:  # pragma: no cover - dependency not installed
            raise RuntimeError(
                "The 'requests' library is required to download site HTML. "
                "Install requests or supply a custom fetch_html callable."
            )

        http_session = session or requests.Session()

        def _fetch(site: Site) -> tuple[str, Optional[Path]]:
            return _download_site_html(
                http_session,
                site,
                headers=headers,
                download_dir=download_dir,
            )

        fetch_html = _fetch

    site_results: List[SiteProcessingResult] = []

    for site in sites:
        html_path: Optional[Path] = None
        try:
            html_text, html_path = fetch_html(site)
            units = extract_units(html_text, site.url)
            filtered_units = filter_units(
                units,
                min_bedrooms=min_bedrooms,
                max_rent=max_rent,
                neighborhoods=neighborhoods,
            )
            site_results.append(
                SiteProcessingResult(
                    site=site,
                    units=filtered_units,
                    html_path=html_path,
                    error=None,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive logging branch
            logging.debug("Error while processing site %s", site.slug, exc_info=True)
            site_results.append(
                SiteProcessingResult(site=site, units=[], html_path=html_path, error=exc)
            )

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


def _download_site_html(
    session: "_requests.Session",
    site: Site,
    *,
    headers: Optional[dict[str, str]] = None,
    download_dir: Optional[Path] = None,
    timeout: float = 20.0,
) -> tuple[str, Optional[Path]]:
    """Download the HTML for *site* and optionally persist it to *download_dir*."""

    response = session.get(site.url, headers=headers, timeout=timeout)
    response.raise_for_status()
    html_text = response.text
    html_path: Optional[Path] = None

    if download_dir is not None:
        download_dir.mkdir(parents=True, exist_ok=True)
        html_path = download_dir / f"{site.slug}.html"
        html_path.write_text(html_text, encoding="utf-8")

    return html_text, html_path


__all__ = [
    "SiteProcessingResult",
    "WorkflowResult",
    "collect_units_from_sites",
    "filter_units",
]

