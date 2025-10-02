import json
from typing import Any, Dict, List, Tuple

import pytest

from parser.scrapers.amsires_scraper import (
    API_URL,
    SEARCH_URL,
    fetch_units,
    parse_appfolio_json,
)


class DummyResponse:
    def __init__(
        self,
        *,
        url: str,
        text: str = "",
        status_code: int = 200,
        json_data: Any | None = None,
    ) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("no json data available")
        return self._json_data


class DummySession:
    def __init__(self, responses: List[DummyResponse]) -> None:
        self._responses = responses
        self.headers: Dict[str, str] = {}
        self.calls: List[Tuple[str, Dict[str, str] | None, int | None]] = []

    def get(
        self,
        url: str,
        *,
        params: Dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> DummyResponse:
        self.calls.append((url, params, timeout))
        assert self._responses, "unexpected HTTP call"
        response = self._responses.pop(0)
        assert response.url == url
        return response


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
    assert pytest.approx(first.bedrooms or 0) == 2
    assert pytest.approx(first.bathrooms or 0) == 1
    assert first.neighborhood == "SOMA"

    assert second.address == "456 Market St"
    assert second.rent == 3450
    assert second.source_url == "https://www.amsires.com/vacancies/unit-2"
    assert pytest.approx(second.bedrooms or 0) == 3
    assert pytest.approx(second.bathrooms or 0) == 2


def test_fetch_units_queries_json_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    api_payload = {
        "data": {
            "items": [
                {
                    "attributes": {
                        "address": {"value": "789 Mission St"},
                        "beds": {"value": "1"},
                        "baths": {"value": "1"},
                        "rent": {"value": "$3,000"},
                        "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-3"},
                    }
                }
            ]
        }
    }

    responses = [
        DummyResponse(url=SEARCH_URL),
        DummyResponse(url=API_URL, text=json.dumps(api_payload), json_data=api_payload),
    ]
    session = DummySession(responses)

    monkeypatch.setattr("requests.Session", lambda: session)

    units = fetch_units(timeout=5, page_size=2, language="ENGLISH")

    assert len(units) == 1
    assert units[0].address == "789 Mission St"
    assert units[0].rent == 3000
    assert units[0].source_url == "https://amsires.appfolio.com/listings/detail/unit-3"

    assert len(session.calls) == 2
    warmup_call, api_call = session.calls
    assert warmup_call[0] == SEARCH_URL
    assert api_call[0] == API_URL
    assert api_call[1] == {"page": "{\"pageSize\":2,\"pageNumber\":0}", "language": "ENGLISH"}
    assert api_call[2] == 5


def test_fetch_units_handles_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    page0 = {
        "items": [
            {
                "attributes": {
                    "address": {"value": "Unit 1"},
                    "beds": {"value": "1"},
                    "baths": {"value": "1"},
                    "rent": {"value": "$2000"},
                    "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-1"},
                }
            },
            {
                "attributes": {
                    "address": {"value": "Unit 2"},
                    "beds": {"value": "2"},
                    "baths": {"value": "2"},
                    "rent": {"value": "$4000"},
                    "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-2"},
                }
            },
        ]
    }

    page1 = {
        "items": [
            {
                "attributes": {
                    "address": {"value": "Unit 3"},
                    "beds": {"value": "3"},
                    "baths": {"value": "2"},
                    "rent": {"value": "$4500"},
                    "listingUrl": {"value": "https://amsires.appfolio.com/listings/detail/unit-3"},
                }
            }
        ]
    }

    responses = [
        DummyResponse(url=SEARCH_URL),
        DummyResponse(url=API_URL, text=json.dumps(page0), json_data=page0),
        DummyResponse(url=API_URL, text=json.dumps(page1), json_data=page1),
    ]
    session = DummySession(responses)
    monkeypatch.setattr("requests.Session", lambda: session)

    units = fetch_units(timeout=10, page_size=2, max_pages=3)

    assert [unit.address for unit in units] == ["Unit 1", "Unit 2", "Unit 3"]
    assert len(session.calls) == 3
    assert session.calls[1][1] == {"page": "{\"pageSize\":2,\"pageNumber\":0}", "language": "ENGLISH"}
    assert session.calls[2][1] == {"page": "{\"pageSize\":2,\"pageNumber\":1}", "language": "ENGLISH"}
