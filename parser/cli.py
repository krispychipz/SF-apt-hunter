"""Command line interface for the apartment parser."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List

from .extract import extract_units


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract apartment listings from an HTML page")
    parser.add_argument("--html", required=True, type=Path, help="Path to the HTML file")
    parser.add_argument("--url", required=True, help="Source URL of the page")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.debug)

    html_bytes = args.html.read_bytes()
    try:
        html_text = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html_text = html_bytes.decode("utf-8", errors="ignore")

    units = extract_units(html_text, args.url)

    if args.pretty:
        data = [unit.to_dict() for unit in units]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for unit in units:
            print(json.dumps(unit.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
