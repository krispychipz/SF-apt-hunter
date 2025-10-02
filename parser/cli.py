"""Command line interface for the apartment parser."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List

from .extract import extract_units
from .scrapers import available_scrapers, available_sites
from .workflow import WorkflowResult, collect_units_from_sites, filter_units

def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract apartment listings from an HTML page")
    parser.add_argument("--html", type=Path, help="Path to the HTML file")
    parser.add_argument("--url", help="Source URL of the page")
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
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.debug)

    neighborhoods = (
        {name.strip().lower() for name in args.neighborhoods}
        if args.neighborhoods
        else None
    )

    if args.html and not args.url:
        print("Error: --url is required when --html is provided.")
        return 1
    if args.url and not args.html:
        print("Error: --html is required when --url is provided.")
        return 1

    if not args.html and not args.url:
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
            scrapers=registry,
        )

        for site_result in result.site_results:
            if site_result.error is None:
                logging.info(
                    "Extracted %s matching unit(s) from %s",
                    len(site_result.units),
                    site_result.site.url or site_result.site.slug,
                )
            else:
                logging.error(
                    "Failed to process %s: %s",
                    site_result.site.url or site_result.site.slug,
                    site_result.error,
                )

        _emit_units(result, args.pretty)
        return 0

    html_bytes = args.html.read_bytes()
    try:
        html_text = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html_text = html_bytes.decode("utf-8", errors="ignore")

    units = extract_units(html_text, args.url)
    units = filter_units(
        units,
        min_bedrooms=args.min_bedrooms,
        max_rent=args.max_rent,
        neighborhoods=neighborhoods,
    )

    _emit_units(WorkflowResult.single_batch(units), args.pretty)
    return 0


def _emit_units(result: WorkflowResult, pretty: bool) -> None:
    units = result.units
    if pretty:
        data = [unit.to_dict() for unit in units]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for unit in units:
            print(json.dumps(unit.to_dict(), ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
