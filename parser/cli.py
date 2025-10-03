"""Command line interface for the apartment parser."""

from __future__ import annotations

import argparse
import json
import logging
import logging.config
from pathlib import Path
from typing import List

from .scrapers import available_scrapers, available_sites
from .workflow import collect_units_from_sites

# Silence noisy HTTP client loggers only
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.CRITICAL)
logging.getLogger("h2").setLevel(logging.CRITICAL)
logging.getLogger("hpack").setLevel(logging.CRITICAL)
logging.getLogger("hyper").setLevel(logging.CRITICAL)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract apartment listings from supported sites")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument(
        "--min-bedrooms",
        type=float,
        help="Minimum number of bedrooms required for a unit to be emitted",
    )
    parser.add_argument(
        "--max-rent",
        type=int,
        help="Maximum monthly rent allowed for a unit to be emitted",
    )
    parser.add_argument(
        "--neighborhood",
        dest="neighborhoods",
        action="append",
        help="Neighborhoods to include (repeat for multiple neighborhoods)",
    )
    parser.add_argument(
        "--zip-code",
        dest="zip_codes",
        action="append",
        help="Zip codes to include (repeat for multiple zip codes)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write extracted units to this JSON file",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.debug)

    neighborhoods = (
        {name.strip().lower() for name in args.neighborhoods}
        if args.neighborhoods
        else None
    )
    zip_codes = (
        {code for code in (item.strip() for item in args.zip_codes) if code}
        if args.zip_codes
        else None
    )

    # Batch mode only: run all available scrapers over HTTP
    registry = available_scrapers()
    if not registry:
        logging.error("No scrapers are available to run.")
        return 1

    sites = available_sites()
    result = collect_units_from_sites(
        sites,
        min_bedrooms=args.min_bedrooms,
        max_rent=args.max_rent,
        neighborhoods=neighborhoods,
        zip_codes=zip_codes,
        scrapers=registry,
    )

    for site_result in result.site_results:
        if site_result.error is None:
            total_extracted = getattr(site_result, "total_extracted", None)
            if total_extracted is None:
                total_extracted = len(site_result.units)

            logging.info(
                "Site: %s\n  Extracted: %d unit(s)\n  Matching criteria: %d unit(s)",
                site_result.site.url or site_result.site.slug,
                total_extracted,
                len(site_result.units),
            )

            if total_extracted == 0:
                logging.debug(
                    "No listing containers matched for site '%s'. See scraper debug logs for selector details.",
                    site_result.site.slug,
                )
        else:
            logging.error(
                "Failed to process %s: %s",
                site_result.site.url or site_result.site.slug,
                site_result.error,
            )

    # Write JSON if requested
    if args.out:
        payload = []
        for site_result in result.site_results:
            payload.append({
                "site": site_result.site.slug,
                "url": site_result.site.url,
                "extracted": getattr(site_result, "total_extracted", len(site_result.units)),
                "matching": len(site_result.units),
                "error": str(site_result.error) if site_result.error else None,
                "units": [u.to_dict() for u in site_result.units],
            })
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None),
            encoding="utf-8",
        )
        logging.info("Wrote JSON to %s", args.out)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
