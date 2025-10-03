"""Tests for the RentBT San Francisco scraper."""

from __future__ import annotations

import textwrap

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
