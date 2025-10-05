"""Tests for the Gaetani Real Estate scraper."""

from parser.scrapers.gaetanirealestate_scraper import (
    LISTINGS_URL,
    parse_appfolio_collection,
)


def test_parse_appfolio_collection_extracts_fields():
    payload = {
        "data": {
            "values": [
                {
                    "page_item_url": "f08f7765-cd75-4b14-bf59-26fa00e923b6",
                    "data": {
                        "full_address": "1409-1421 Sacramento St., 1409, San Francisco, CA 94118",
                        "bedrooms": 2,
                        "bathrooms": 2,
                        "market_rent": 4695,
                        "database_url": "https://gaetanirealestate.appfolio.com/",
                        "listable_uid": "f08f7765-cd75-4b14-bf59-26fa00e923b6",
                        "rental_application_url": (
                            "https://gaetanirealestate.appfolio.com/listings/rental_applications/new"
                            "?listable_uid=f08f7765-cd75-4b14-bf59-26fa00e923b6&source=Website"
                        ),
                    },
                }
            ]
        }
    }

    units = parse_appfolio_collection(payload, base_url=LISTINGS_URL)
    assert len(units) == 1
    unit = units[0]
    assert (
        unit.address
        == "1409-1421 Sacramento St., 1409, San Francisco, CA 94118"
    )
    assert unit.bedrooms == 2
    assert unit.bathrooms == 2
    assert unit.rent == 4695
    assert unit.source_url == (
        "https://gaetanirealestate.appfolio.com/listings/detail/"
        "f08f7765-cd75-4b14-bf59-26fa00e923b6"
    )


def test_parse_appfolio_collection_handles_missing_details():
    payload = {
        "values": [
            {
                "data": {
                    "address_address1": "1 Main St",
                    "address_city": "San Francisco",
                    "address_state": "CA",
                    "address_postal_code": "94109",
                    "bedrooms": "2 Beds",
                    "bathrooms": "1 Bath",
                    "market_rent": "2,750",
                    "rental_application_url": "https://example.com/apply",
                }
            },
            {"data": {"bathrooms": None}},
        ]
    }

    units = parse_appfolio_collection(payload, base_url=LISTINGS_URL)
    assert len(units) == 1
    unit = units[0]
    assert unit.address == "1 Main St, San Francisco, CA, 94109"
    assert unit.bedrooms == 2
    assert unit.bathrooms == 1
    assert unit.rent == 2750
    assert unit.source_url == "https://example.com/apply"
