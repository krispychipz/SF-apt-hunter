"""Tests for the Anchor Realty scraper."""

from parser.scrapers.anchorealty_scraper import LISTINGS_URL, parse_listings


def test_parse_listings_extracts_core_fields():
    html = """
    <div class="listing-item" id="listing_514">
        <div class="listing-item__figure-container">
            <a href="/listings/detail/fc8f831b-268d-4da3-99ba-a669670d39b7">
                <div class="listing-item__figure">
                    <div class="listing-item__blurb">
                        <div class="rent-banner__text js-listing-blurb-rent">$2,595</div>
                        <span class="rent-banner__text js-listing-blurb-bed-bath">Studio / 1 ba</span>
                    </div>
                </div>
            </a>
        </div>
        <div class="listing-item__body">
            <h2 class="listing-item__title">
                <a href="/listings/detail/fc8f831b-268d-4da3-99ba-a669670d39b7">
                    Renovated Nob Hill Studio with In Unit Laundry!
                </a>
            </h2>
            <p>
                <span class="u-pad-rm js-listing-address">
                    1684 Washington Street #2, San Francisco, CA 94109
                </span>
            </p>
        </div>
    </div>
    """

    units = parse_listings(html, base_url=LISTINGS_URL)
    assert len(units) == 1

    unit = units[0]
    assert unit.address == "1684 Washington Street #2, San Francisco, CA 94109"
    assert unit.rent == 2595
    assert unit.bedrooms == 0
    assert unit.bathrooms == 1
    assert unit.source_url == (
        "https://anchorealtyinc.com/listings/detail/"
        "fc8f831b-268d-4da3-99ba-a669670d39b7"
    )


def test_parse_listings_handles_missing_values():
    html = """
    <div>
        <div class="listing-item">
            <div class="listing-item__body">
                <span class="js-listing-address">1200 Pine St</span>
            </div>
        </div>
        <div class="listing-item">
            <a href="/listings/detail/abc"></a>
        </div>
    </div>
    """

    units = parse_listings(html, base_url=LISTINGS_URL)
    assert len(units) == 2

    first, second = units
    assert first.address == "1200 Pine St"
    assert first.rent is None
    assert first.bedrooms is None
    assert first.bathrooms is None

    assert second.address is None
    assert second.source_url == "https://anchorealtyinc.com/listings/detail/abc"
