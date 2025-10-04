from bs4 import BeautifulSoup


from parser.scrapers import structure_scraper as ss


def _make_block(html: str):
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one(".listing")


def test_parse_showmojo_listing_block_extracts_key_fields():
    block = _make_block(
        """
        <div class="listing">
          <div class="listing-info-header">
            <div class="listing-address-header">693 Sutter Street #602</div>
            <div class="listing-city-state-zip">San Francisco, CA 94102</div>
          </div>
          <div class="listing-icons">
            <div class="listing-icon-wrap">
              <img class="icon" src="https://assets.prod.showmojo.com/.../bed-123.svg" alt="bed icon">
              <div class="listing-icons-data">3</div>
            </div>
            <div class="listing-icon-wrap">
              <img class="icon" src="https://assets.prod.showmojo.com/.../bath-123.svg" alt="bath icon">
              <div class="listing-icons-data">2</div>
            </div>
          </div>
          <div class="rent-info">
            <span class="price">$7,895</span>
            &nbsp;/mo
          </div>
          <a class="js-wsi-schedule-link js-view-listing-link listing-button customizable-color" href="/l/187f53406c/693-sutter-street-602-san-francisco-ca-94102?g=2&amp;sd=true">View Listing</a>
        </div>
        """
    )

    rent = ss._extract_rent(block)
    beds = ss._extract_beds(block)
    url = ss._extract_url(block, "https://mapsearch.showmojo.com")

    assert rent == 7895
    assert beds == 3
    assert (
        url
        == "https://mapsearch.showmojo.com/l/187f53406c/693-sutter-street-602-san-francisco-ca-94102?g=2&sd=true"
    )
