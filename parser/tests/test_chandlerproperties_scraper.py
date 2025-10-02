"""Tests for the Chandler Properties scraper."""

from parser.scrapers.chandlerproperties_scraper import LISTINGS_URL, parse_listings


def test_parse_listings_extracts_basic_fields():
    html = """
    <div class="listing-item">
        <a href="?lid=341f0480-5bd8-4b70-bde1-304203b1ac0f">
            <div class="list-img">
                <span class="rent-price">$5,850</span>
            </div>
        </a>
        <div class="details">
            <h3 class="address">1330 Jones St. Apt 601, San Francisco, CA 94109</h3>
            <p>
                <span class="beds">2 Beds</span>
                <span class="baths">1 Baths</span>
            </p>
        </div>
    </div>
    """

    units = parse_listings(html, base_url=LISTINGS_URL)
    assert len(units) == 1
    unit = units[0]
    assert unit.address == "1330 Jones St. Apt 601, San Francisco, CA 94109"
    assert unit.rent == 5850
    assert unit.bedrooms == 2
    assert unit.bathrooms == 1
    assert unit.source_url == (
        "https://chandlerproperties.com/rental-listings/?lid=341f0480-5bd8-4b70-bde1-304203b1ac0f"
    )


def test_parse_listings_handles_missing_values():
    html = """
    <div>
        <div class="listing-item">
            <div class="details">
                <h3 class="address">145 Oak St, San Francisco, CA 94102</h3>
            </div>
        </div>
        <div class="listing-item">
            <a href="/rental-listings/?lid=123"></a>
            <div class="details"></div>
        </div>
    </div>
    """

    units = parse_listings(html, base_url=LISTINGS_URL)
    assert len(units) == 2

    first, second = units
    assert first.address == "145 Oak St, San Francisco, CA 94102"
    assert first.rent is None
    assert first.bedrooms is None
    assert first.bathrooms is None

    assert second.address is None
    assert second.source_url == "https://chandlerproperties.com/rental-listings/?lid=123"
