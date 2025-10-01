"""Command line interface for the apartment parser."""

from __future__ import annotations

import argparse
import json
import logging
import requests
from pathlib import Path
from typing import List

from .extract import extract_units
from .sites import load_sites_yaml
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/117.0.0.0 Safari/537.36"
}

def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract apartment listings from an HTML page")
    parser.add_argument("--html", type=Path, help="Path to the HTML file")
    parser.add_argument("--url", help="Source URL of the page")
    parser.add_argument("--sites-yaml", type=Path, help="Path to a YAML file containing site URLs")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.debug)

    if args.sites_yaml:
        sites = load_sites_yaml(args.sites_yaml)
        for site in sites:
            print(f"Extracting from {site.url}...")
            try:
                response = requests.get(site.url, headers=headers)
                response.raise_for_status()
                html_text = response.text
                units = extract_units(html_text, site.url)
                for unit in units:
                    print(json.dumps(unit.to_dict(), ensure_ascii=False))
            except Exception as e:
                print(f"Failed to extract from {site.url}: {e}")
        return 0
    
    if not args.html or not args.url:
        print("Error: --html and --url are required unless --sites-yaml is used.")
        return 1
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
