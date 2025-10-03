"""Tests for the RentBT San Francisco scraper."""

from __future__ import annotations

import textwrap
from typing import Dict, Optional

import requests

from parser.scrapers import rentbt_sf_scraper as scraper


def test_parse_listings_handles_result_body_wrapper():
    html = textwrap.dedent(
        """
        <div class="resultBody">
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
        </div>
        """
    )

    units = scraper.parse_listings(html, base_url="https://properties.rentbt.com/searchlisting.aspx")

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


def test_fetch_units_has_custom_default_url():
    assert scraper.fetch_units.default_url == scraper.BASE_URL  # type: ignore[attr-defined]


def test_fetch_units_debug_hook_and_header_profile():
    events = []

    class FakeResponse:
        def __init__(self, text: str, cookies: Optional[Dict[str, str]] = None) -> None:
            self.text = text
            jar = requests.cookies.RequestsCookieJar()
            for key, value in (cookies or {}).items():
                jar.set(key, value)
            self.cookies = jar

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.headers: Dict[str, str] = {}
            self.cookies = requests.cookies.RequestsCookieJar()
            self.calls = []

        def get(self, url, headers=None, timeout=None, **kwargs):
            self.calls.append((url, headers or {}))
            if url == scraper.LANDING_URL:
                return FakeResponse("<html></html>", cookies={"ASP.NET_SessionId": "abc"})
            if url == scraper.SEARCH_FORM_URL:
                return FakeResponse("<input type='hidden' name='ftst' value='token' />")
            return FakeResponse(
                """
                <div class="property-details prop-listing-box">
                  <div class="parameters hidden mapPoint">
                    <span class="propertyAddress">Address</span>
                    <span class="propertyMinRent">1234</span>
                  </div>
                  <div class="prop-details">
                    <a class="propertyUrl" href="/listing" />
                  </div>
                </div>
                """
            )

    def debug_hook(phase, payload):
        events.append((phase, payload))

    session = FakeSession()

    scraper.fetch_units(
        pages=1,
        delay=0,
        session=session,
        debug=debug_hook,
        header_profile="minimal",
    )

    assert any(phase == "session_headers" for phase, _ in events)
    tokens_event = next(payload for phase, payload in events if phase == "tokens")
    assert tokens_event["tokens"]["ftst"] == "token"
    assert "ftst=token" in tokens_event["merged_url"]

    page_event = next(payload for phase, payload in events if phase == "page")
    assert page_event["unit_count"] == 1
    assert page_event["cookies"]["ASP.NET_SessionId"] == "abc"

    minimal_headers = scraper.HEADER_PROFILES["minimal"]
    for _, headers in session.calls:
        for key in minimal_headers:
            assert headers[key] == minimal_headers[key]
        assert "Sec-Fetch-Site" not in headers
