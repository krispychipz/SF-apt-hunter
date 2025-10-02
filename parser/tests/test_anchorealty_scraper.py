"""Tests for the Anchor Realty scraper."""

from parser.scrapers.anchorealty_scraper import LISTINGS_URL, parse_listings


def test_parse_listings_extracts_core_fields():
    html = """
    <div class="listing-card" data-testid="listing-card">
        <a class="listing-card__link" href="/listings/detail/fc8f831b-268d-4da3-99ba-a669670d39b7">
            <div class="listing-card__header">
                <h3 class="listing-card__title">Renovated Nob Hill Studio with In Unit Laundry!</h3>
                <div class="listing-card__address" data-testid="listing-card-address">
                    1684 Washington Street #2, San Francisco, CA 94109
                </div>
            </div>
            <div class="listing-card__rent" data-testid="listing-card-rent">$2,595 / month</div>
            <div class="listing-card__details">
                <span data-testid="listing-card-bed-bath">Studio / 1 ba</span>
            </div>
        </a>
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
        "https://anchorrlty.appfolio.com/listings/detail/"
        "fc8f831b-268d-4da3-99ba-a669670d39b7"
    )


def test_parse_listings_handles_missing_values():
    html = """
    <div>
        <div class="listing-card" data-testid="listing-card" data-address="1200 Pine St">
            <div class="listing-card__details"></div>
        </div>
        <div class="listing-card">
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
    assert second.source_url == "https://anchorrlty.appfolio.com/listings/detail/abc"
