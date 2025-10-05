"""Tests for the RentSFNow scraper."""

from __future__ import annotations

import textwrap

from parser.scrapers import rentsfnow_scraper as scraper


def test_parse_listings_extracts_details():
    html = textwrap.dedent(
        """
        <div class="cell small-12 medium-12 large-6 searchDetailSpacing">
            <a href="/apartments/rental/721-geary-28">
                <h3>Downtown</h3>
                <h2>721 Geary #28</h2>
                <p class="apartment-info">
                    2 Beds \\ 1 Bath \\ $3,265
                </p>
            </a>
        </div>
        """
    )

    units = scraper.parse_listings(html, base_url=scraper.DEFAULT_URL)

    assert len(units) == 1
    unit = units[0]
    assert unit.address == "721 Geary #28"
    assert unit.neighborhood == "Downtown"
    assert unit.bedrooms == 2
    assert unit.bathrooms == 1
    assert unit.rent == 3265
    assert unit.source_url == "https://www.rentsfnow.com/apartments/rental/721-geary-28"


def test_build_payload_derives_parameters_from_url():
    url = (
        "https://www.rentsfnow.com/apartments/rentals/"
        "?bedrooms=2&max_price=3600&neighborhood=Mission"
    )

    payload, referer = scraper.build_payload(url)

    assert referer.startswith("https://www.rentsfnow.com/apartments/rentals/")
    assert payload["bedrooms"] == "2"
    assert payload["max_price"] == "3600"
    assert payload["neighborhood"] == "Mission"
    assert payload["action"] == "filter_properties"


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None


class _StubSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, dict[str, str], dict[str, str], int]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        headers: dict[str, str],
        timeout: int,
    ) -> _StubResponse:
        self.calls.append((url, data, headers, timeout))
        return _StubResponse(self.text)

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def test_fetch_units_posts_to_ajax_endpoint_with_payload():
    html = textwrap.dedent(
        """
        <div class="cell small-12 medium-12 large-6 searchDetailSpacing">
            <a href="/apartments/rental/example-unit">
                <h3>Mission</h3>
                <h2>123 Mission St</h2>
                <p class="apartment-info">2 Beds \\ 1 Bath \\ $3,100</p>
            </a>
        </div>
        """
    )

    session = _StubSession(html)
    url = "https://www.rentsfnow.com/apartments/rentals/?bedrooms=2&max_price=3100"

    units = scraper.fetch_units(url, session=session, timeout=10)

    assert len(units) == 1
    assert session.calls, "Expected at least one POST request"

    called_url, data, headers, timeout = session.calls[0]
    assert called_url == scraper.AJAX_ENDPOINT
    assert data["bedrooms"] == "2"
    assert data["max_price"] == "3100"
    assert headers["Referer"].startswith("https://www.rentsfnow.com/apartments/rentals/")
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert timeout == 10


def test_apply_filter_params_updates_querystring():
    base = "https://www.rentsfnow.com/apartments/rentals/"

    updated = scraper.apply_filter_params(
        base,
        min_bedrooms=2.4,
        max_rent=3300,
        neighborhoods={"SOMA"},
    )

    assert "bedrooms=3" in updated
    assert "max_price=3300" in updated
    assert "neighborhood=SOMA" in updated

