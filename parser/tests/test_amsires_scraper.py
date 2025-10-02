import json
from typing import Any, Dict, List

import pytest
import requests

from parser.scrapers.amsires_scraper import (
    SEARCH_URL,
    fetch_units,
    parse_appfolio_json,
)


class DummyResponse:
    def __init__(
        self,
        *,
        url: str,
        text: str,
        headers: Dict[str, str] | None = None,
        status_code: int = 200,
        json_data: Any | None = None,
    ) -> None:
        self.url = url
        self.text = text
        self.headers = headers or {}
        self.status_code = status_code
        self._json_data = json_data
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        if 400 <= self.status_code:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("no json data")
        return self._json_data


def test_parse_appfolio_json_extracts_units() -> None:
    api_data = {
        "data": {
            "items": [
                {
                    "attributes": {
                        "address": {"value": "123 Main St"},
                        "beds": {"value": "2"},
                        "baths": {"value": "1"},
                        "rent": {"value": "$2,500"},
                        "neighborhood": {"value": "SOMA"},
                        "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-1"},
                    }
                },
                {
                    "attributes": {
                        "location": {"text": "456 Market St"},
                        "bedrooms": {"values": ["3"]},
                        "bathrooms": {"value": 2},
                        "price": {"rawValue": "3450"},
                        "website": {"value": "/vacancies/unit-2"},
                    }
                },
            ]
        }
    }

    units = parse_appfolio_json(api_data, base_url=SEARCH_URL)
    assert len(units) == 2

    first, second = units
    assert first.address == "123 Main St"
    assert first.rent == 2500
    assert first.source_url == "https://amsires.appfolio.com/listings/detail/unit-1"
    assert pytest.approx(first.bedrooms) == 2
    assert pytest.approx(first.bathrooms) == 1
    assert first.neighborhood == "SOMA"

    assert second.address == "456 Market St"
    assert second.rent == 3450
    assert second.source_url == "https://www.amsires.com/vacancies/unit-2"
    assert pytest.approx(second.bedrooms or 0) == 3
    assert pytest.approx(second.bathrooms or 0) == 2


def test_fetch_units_falls_back_to_api(monkeypatch: pytest.MonkeyPatch) -> None:
    api_url = (
        "https://www.amsires.com/rts/collections/public/test/runtime/collection/"
        "appfolio-listings/data?page=%7B%22pageSize%22%3A100%2C%22pageNumber%22%3A0%7D&language=ENGLISH"
    )

    html = (
        '<html><head></head><body>'
        f'<script>fetch("{api_url}")</script>'
        '</body></html>'
    )

    api_payload = {
        "data": {
            "items": [
                {
                    "attributes": {
                        "location": {"value": "789 Mission St"},
                        "beds": {"value": "1"},
                        "baths": {"value": "1"},
                        "rent": {"value": "$3,000"},
                        "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-3"},
                    }
                }
            ]
        },
        "page": {"pageNumber": 0, "totalPages": 1},
    }

    responses: List[DummyResponse] = [
        DummyResponse(url=SEARCH_URL, text=html, headers={"Content-Type": "text/html"}),
        DummyResponse(
            url=api_url,
            text=json.dumps(api_payload),
            headers={"Content-Type": "application/json"},
            json_data=api_payload,
        ),
    ]

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> DummyResponse:
        assert responses, "unexpected extra HTTP call"
        response = responses.pop(0)
        assert response.url == url
        if "appfolio-listings" in url:
            assert "application/json" in headers.get("Accept", "")
        else:
            assert "text/html" in headers.get("Accept", "")
        assert timeout == 5
        return response

    monkeypatch.setattr("requests.get", fake_get)

    units = fetch_units(SEARCH_URL, timeout=5)
    assert len(units) == 1
    assert units[0].address == "789 Mission St"
    assert units[0].rent == 3000
    assert units[0].source_url == "https://amsires.appfolio.com/listings/detail/unit-3"


def test_fetch_units_handles_api_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    base_api = (
        "https://www.amsires.com/rts/collections/public/test/runtime/collection/"
        "appfolio-listings/data?page=%7B%22pageSize%22%3A100%2C%22pageNumber%22%3A0%7D&language=ENGLISH"
    )

    html = (
        '<html><body><script>'
        f'const endpoint = "{base_api}";'
        "</script></body></html>"
    )

    page0 = {
        "data": {
            "items": [
                {
                    "attributes": {
                        "address": {"value": "Unit 1"},
                        "beds": {"value": "1"},
                        "baths": {"value": "1"},
                        "price": {"value": "$2000"},
                        "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-1"},
                    }
                }
            ]
        },
        "page": {"pageNumber": 0, "totalPages": 2},
    }

    page1 = {
        "data": {
            "items": [
                {
                    "attributes": {
                        "address": {"value": "Unit 2"},
                        "beds": {"value": "2"},
                        "baths": {"value": "2"},
                        "rent": {"value": "$4000"},
                        "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-2"},
                    }
                }
            ]
        },
        "page": {"pageNumber": 1, "totalPages": 2},
    }

    encoded_next = (
        "https://www.amsires.com/rts/collections/public/test/runtime/collection/"
        "appfolio-listings/data?page=%7B%22pageSize%22%3A100%2C%22pageNumber%22%3A1%7D&language=ENGLISH"
    )

    responses: List[DummyResponse] = [
        DummyResponse(url=SEARCH_URL, text=html, headers={"Content-Type": "text/html"}),
        DummyResponse(
            url=base_api,
            text=json.dumps(page0),
            headers={"Content-Type": "application/json"},
            json_data=page0,
        ),
        DummyResponse(
            url=encoded_next,
            text=json.dumps(page1),
            headers={"Content-Type": "application/json"},
            json_data=page1,
        ),
    ]

    def fake_get(url: str, *, headers: Dict[str, str], timeout: int) -> DummyResponse:
        assert responses, "unexpected extra HTTP call"
        response = responses.pop(0)
        assert response.url == url
        return response

    monkeypatch.setattr("requests.get", fake_get)

    units = fetch_units(SEARCH_URL)
    assert [unit.address for unit in units] == ["Unit 1", "Unit 2"]
    assert units[0].rent == 2000
    assert units[1].rent == 4000
