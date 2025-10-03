"""Tests for the RentBT scraper."""

from __future__ import annotations

import textwrap

import requests

from parser.scrapers.rentbt_scraper import (
    HEADERS,
    LANDING_URL,
    _get_page,
    parse_listings,
    set_page_number,
)


def test_parse_listings_extracts_key_fields():
    html = textwrap.dedent(
        """
        <div class="property-details prop-listing-box">
          <div class="parameters hidden mapPoint">
            <span class="propertyAddress">1395 Golden Gate Avenue San Francisco CA 94115</span>
            <span class="propertyMinRent">3445.00</span>
          </div>
          <div class="prop-address">
            <span class="propertyAddress">1395 Golden Gate Avenue</span>
            <span class="propertyCity">San Francisco</span>
            <span class="propertyState">CA</span>
            <span class="propertyZipCode">94115</span>
          </div>
          <div class="display-icons">
            <ul>
              <li class="prop-rent">$<span class="propertyMaxRent">3445</span></li>
              <li class="prop-beds"><span class="propertyMinBed">Studio</span> - <span class="propertyMaxBed">2</span></li>
              <li class="prop-baths"><span class="propertyMinBath">1</span></li>
            </ul>
          </div>
          <div class="prop-details">
            <a class="propertyUrl" href="/apartments/ca/san-francisco/1395-golden-gate-avenue-owner-lp/default.aspx">Details</a>
          </div>
        </div>
        """
    )

    units = parse_listings(html, base_url="https://properties.rentbt.com/searchlisting.aspx")

    assert len(units) == 1
    unit = units[0]
    assert unit.address == "1395 Golden Gate Avenue San Francisco CA 94115"
    assert unit.rent == 3445
    assert unit.bedrooms == 2
    assert unit.bathrooms == 1
    assert (
        unit.source_url
        == "https://properties.rentbt.com/apartments/ca/san-francisco/1395-golden-gate-avenue-owner-lp/default.aspx"
    )


def test_set_page_number_updates_querystring():
    base = "https://properties.rentbt.com/searchlisting.aspx?PgNo=1&txtCity=san%20francisco"
    second = set_page_number(base, 2)
    assert "PgNo=2" in second
    first = set_page_number(second, 1)
    assert "PgNo=" not in first


def test_headers_include_modern_chrome_fields():
    assert "Upgrade-Insecure-Requests" in HEADERS
    assert "Sec-Fetch-Site" in HEADERS
    assert "Sec-Fetch-Mode" in HEADERS
    assert "Sec-Fetch-User" in HEADERS
    assert "Sec-Fetch-Dest" in HEADERS
    assert HEADERS.get("sec-ch-ua") is not None
    assert HEADERS.get("sec-ch-ua-mobile") == "?0"
    assert HEADERS.get("sec-ch-ua-platform") == '"Windows"'
    assert "Referer" not in HEADERS


class _StubResponse:
    def __init__(self, url: str, headers: dict[str, str]):
        self.url = url
        self._headers = headers
        self.text = "ok"
        self.cookies = requests.cookies.RequestsCookieJar()

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url: str, headers: dict[str, str], timeout: int):
        self.calls.append((url, headers))
        return _StubResponse(url, headers)


def test_get_page_populates_referer_header_by_default():
    client = _StubClient()

    _get_page(LANDING_URL, client=client, timeout=5)

    assert client.calls, "Expected at least one request to be recorded"
    first_url, first_headers = client.calls[0]
    assert first_url == LANDING_URL
    assert first_headers["Referer"] == LANDING_URL

    next_url = set_page_number(first_url, 2)
    _get_page(next_url, client=client, timeout=5, referer=first_url)

    assert len(client.calls) == 2
    _, second_headers = client.calls[1]
    assert second_headers["Referer"] == first_url
