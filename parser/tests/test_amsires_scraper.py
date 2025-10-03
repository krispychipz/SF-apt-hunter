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
        "name": "appfolio-listings",
        "values": [
            {
                "data": {
                    "full_address": "123 Main St, San Francisco, CA 94105",
                    "bedrooms": 2,
                    "bathrooms": 1.5,
                    "market_rent": 4200,
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "abc123",
                    "address_city": "San Francisco",
                }
            },
            {
                "data": {
                    "address_address1": "456 Market St",
                    "address_city": "San Francisco",
                    "address_state": "CA",
                    "address_postal_code": "94107",
                    "bedrooms": "3",
                    "bathrooms": "2",
                    "market_rent": "$5,000",
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "def456",
                    "portfolio_city": "San Francisco",
                }
            },
        ],
    }

    units = parse_appfolio_json(api_data, base_url=SEARCH_URL)
    assert len(units) == 2

    first, second = units
    assert first.address == "123 Main St, San Francisco, CA 94105"
    assert first.rent == 4200
    assert first.source_url == "https://amsires.appfolio.com/listings/detail/abc123"
    assert pytest.approx(first.bedrooms or 0) == 2
    assert pytest.approx(first.bathrooms or 0) == 1.5
    assert first.neighborhood == "San Francisco"

    assert second.address == "456 Market St, San Francisco, CA, 94107"
    assert second.rent == 5000
    assert second.source_url == "https://amsires.appfolio.com/listings/detail/def456"
    assert pytest.approx(second.bedrooms or 0) == 3
    assert pytest.approx(second.bathrooms or 0) == 2
    assert second.neighborhood == "San Francisco"


def test_fetch_units_queries_json_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    api_payload = {
        "name": "appfolio-listings",
        "values": [
            {
                "data": {
                    "full_address": "789 Mission St, San Francisco, CA 94103",
                    "bedrooms": 1,
                    "bathrooms": 1,
                    "market_rent": "$3,000",
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "unit-3",
                    "address_city": "San Francisco",
                }
            }
        ],
    }

    responses = [
        DummyResponse(url=SEARCH_URL),
        DummyResponse(url=API_URL, text=json.dumps(api_payload), json_data=api_payload),
    ]
    session = DummySession(responses)

    monkeypatch.setattr("requests.Session", lambda: session)

    units = fetch_units(timeout=5, page_size=2, language="ENGLISH")

    assert len(units) == 1
    assert units[0].address == "789 Mission St, San Francisco, CA 94103"
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
        "values": [
            {
                "data": {
                    "full_address": "Unit 1",
                    "bedrooms": 1,
                    "bathrooms": 1,
                    "market_rent": "$2000",
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "unit-1",
                }
            },
            {
                "data": {
                    "full_address": "Unit 2",
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "market_rent": "$4000",
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "unit-2",
                }
            },
        ]
    }

    page1 = {
        "values": [
            {
                "data": {
                    "full_address": "Unit 3",
                    "bedrooms": 3,
                    "bathrooms": 2,
                    "market_rent": "$4500",
                    "database_url": "https://amsires.appfolio.com/",
                    "listable_uid": "unit-3",
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
