from __future__ import annotations

import textwrap

from parser.scrapers import mosser_scraper as ms


def test_parse_property_list_returns_urls_and_metadata():
    html = textwrap.dedent(
        """
        <div class="property-card-wrapper">
          <div>
            <a href="https://www.mosserliving.com/apartments/419-pierce/">
              <div class="rentpress-property-card-title">419 Pierce</div>
              <div class="v-card__subtitle">Alamo Square, San Francisco, CA</div>
              <script type="application/ld+json">
              {
                "@context": "https://schema.org/",
                "@type": "ApartmentComplex",
                "address": {
                  "@type": "PostalAddress",
                  "streetAddress": "419 Pierce St",
                  "addressLocality": "San Francisco",
                  "addressRegion": "CA"
                }
              }
              </script>
            </a>
          </div>
        </div>
        """
    )

    results = ms.parse_property_list(html)

    assert len(results) == 1
    url, address, neighborhood = results[0]
    assert url == "https://www.mosserliving.com/apartments/419-pierce/"
    assert address == "419 Pierce St"
    assert neighborhood == "Alamo Square"


def test_parse_property_page_extracts_unit_details():
    html = textwrap.dedent(
        """
        <div class="rentpress-remove-link-decoration">
          <a href="/floorplans/studio-plan-4/">
            <div class="rentpress-shortcode-floorplan-card">
              <div class="v-card__subtitle">
                <div><span> Studio | 1 Bath </span></div>
              </div>
              <div class="v-card__text">
                <div class="rentpress-inherited-font-family text-body-1 font-italic col col-auto">
                  Starting at $2,475
                </div>
              </div>
            </div>
          </a>
        </div>
        """
    )

    units = ms.parse_property_page(
        html,
        property_url="https://www.mosserliving.com/apartments/419-pierce/",
        address="419 Pierce St",
        neighborhood="Alamo Square",
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.address == "419 Pierce St"
    assert unit.bedrooms == 0.0
    assert unit.bathrooms == 1.0
    assert unit.rent == 2475
    assert (
        unit.source_url
        == "https://www.mosserliving.com/floorplans/studio-plan-4/"
    )
    assert unit.neighborhood == "Alamo Square"


def test_parse_property_page_uses_inline_ldjson_payload():
    html = textwrap.dedent(
        """
        <div class="rentpress-remove-link-decoration">
          <a href="/floorplans/junior-1-bedroom-plan-6/">
            <div class="rentpress-shortcode-floorplan-card">
              <div class="v-card__title"> Junior 1 Bedroom - Plan 6 </div>
              <div class="v-card__subtitle"><div><span> </span></div></div>
              <script type="application/ld+json">
              {
                "@context": "https://schema.org/",
                "@type": "Product",
                "about": {
                  "@type": "FloorPlan",
                  "name": "Junior 1 Bedroom - Plan 6",
                  "url": "https://www.mosserliving.com/floorplans/junior-1-bedroom-plan-6/",
                  "numberOfBedrooms": "1",
                  "numberOfBathroomsTotal": "1"
                },
                "offers": {
                  "@type": "AggregateOffer",
                  "lowPrice": "2125",
                  "priceCurrency": "USD"
                }
              }
              </script>
            </div>
          </a>
        </div>
        """
    )

    units = ms.parse_property_page(
        html,
        property_url="https://www.mosserliving.com/apartments/1008-larkin/",
        address="1008 Larkin St",
        neighborhood="Nob Hill",
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.bedrooms == 1.0
    assert unit.bathrooms == 1.0
    assert unit.rent == 2125
    assert unit.source_url == "https://www.mosserliving.com/floorplans/junior-1-bedroom-plan-6/"


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:  # pragma: no cover - trivial stub
        return None


class _StubSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str], timeout: int) -> _StubResponse:
        self.calls.append(url)
        try:
            return _StubResponse(self.pages[url])
        except KeyError as exc:  # pragma: no cover - defensive
            raise AssertionError(f"Unexpected URL requested: {url}") from exc

    def close(self) -> None:  # pragma: no cover - stub behaviour
        return None


def test_fetch_units_aggregates_units_across_properties():
    listing_html = textwrap.dedent(
        """
        <div class="property-card-wrapper">
          <div>
            <a href="https://www.mosserliving.com/apartments/419-pierce/">
              <div class="rentpress-property-card-title">419 Pierce</div>
              <div class="v-card__subtitle">Alamo Square, San Francisco, CA</div>
              <script type="application/ld+json">
              {
                "address": {
                  "streetAddress": "419 Pierce St"
                }
              }
              </script>
            </a>
          </div>
        </div>
        """
    )
    property_html = textwrap.dedent(
        """
        <div class="rentpress-remove-link-decoration">
          <a href="/floorplans/studio-plan-4/">
            <div class="rentpress-shortcode-floorplan-card">
              <div class="v-card__subtitle">
                <div><span> Studio | 1 Bath </span></div>
              </div>
              <div class="v-card__text">
                <div class="rentpress-inherited-font-family text-body-1 font-italic col col-auto">
                  Starting at $2,475
                </div>
              </div>
            </div>
          </a>
        </div>
        """
    )

    pages = {
        ms.DEFAULT_URL: listing_html,
        "https://www.mosserliving.com/apartments/419-pierce/": property_html,
    }
    session = _StubSession(pages)

    units = ms.fetch_units(session=session)

    assert len(units) == 1
    unit = units[0]
    assert unit.rent == 2475
    assert unit.address == "419 Pierce St"
    assert session.calls[0] == ms.DEFAULT_URL
    assert session.calls[1] == "https://www.mosserliving.com/apartments/419-pierce/"
