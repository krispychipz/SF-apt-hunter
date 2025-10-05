import pytest

from parser.scrapers import gaetanirealestate_scraper as scraper


SAMPLE_PAYLOAD = {
    "values": [
        {
            "listing": {
                "full_address": "123 Main St, San Francisco, CA 94109",
                "bedrooms": "2",
                "bathrooms": "1.5",
                "market_rent": "3450",
                "listable_uid": "abc123",
                "database_url": "https://gaetani.appfolio.com/",
            }
        },
        {
            "listing": {
                "address_address1": "456 Oak St",
                "address_city": "San Francisco",
                "address_state": "CA",
                "address_postal_code": "94102",
                "bedrooms": 1,
                "bathrooms": 1,
                "rent": 2800,
                "portfolio_url": "https://gaetani.appfolio.com/listings/detail/xyz789",
            }
        },
    ]
}


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_parse_appfolio_collection_produces_units():
    units = scraper.parse_appfolio_collection(SAMPLE_PAYLOAD, base_url=scraper.LISTINGS_URL)

    assert len(units) == 2
    assert units[0].address == "123 Main St, San Francisco, CA 94109"
    assert units[0].bedrooms == pytest.approx(2)
    assert units[0].bathrooms == pytest.approx(1.5)
    assert units[0].rent == 3450
    assert units[0].source_url.startswith("https://gaetani.appfolio.com/")

    assert units[1].address == "456 Oak St, San Francisco, CA, 94102"
    assert units[1].bedrooms == 1
    assert units[1].bathrooms == 1
    assert units[1].rent == 2800
    assert units[1].source_url == "https://gaetani.appfolio.com/listings/detail/xyz789"


def test_fetch_units_default_url_uses_api_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, *, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse(SAMPLE_PAYLOAD)

    monkeypatch.setattr(scraper.requests, "get", fake_get)

    units = scraper.fetch_units()

    assert captured["url"] == scraper.APPFOLIO_API_URL
    assert captured["headers"] == scraper.HEADERS
    assert captured["timeout"] == 20
    assert len(units) == 2


def test_fetch_units_default_url_attribute_points_to_api():
    assert scraper.fetch_units.default_url == scraper.APPFOLIO_API_URL
