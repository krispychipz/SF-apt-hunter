"""Scraper for Gaetani Real Estate AppFolio listings."""

from __future__ import annotations

from typing import List

import requests

from parser.models import Unit
from parser.scrapers.jacksongroup_scraper import (
    parse_appfolio_collection as _parse_appfolio_collection,
)

LISTINGS_URL = "https://www.gaetanirealestate.com/vacancies"
APPFOLIO_API_URL = (
    "https://www.gaetanirealestate.com/rts/collections/public/"
    "31f9c706/runtime/collection/appfolio-listings/data?page=%7B%22pageSize%22%3A100%2C"
    "%22pageNumber%22%3A0%7D&language=ENGLISH"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

parse_appfolio_collection = _parse_appfolio_collection


def fetch_units(url: str = APPFOLIO_API_URL, *, timeout: int = 20) -> List[Unit]:
    """Fetch Gaetani Real Estate listings from the published AppFolio endpoint."""

    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()

    payload = response.json()
    return parse_appfolio_collection(payload, base_url=LISTINGS_URL)


fetch_units.default_url = APPFOLIO_API_URL  # type: ignore[attr-defined]


__all__ = ["fetch_units", "parse_appfolio_collection", "APPFOLIO_API_URL", "LISTINGS_URL"]
