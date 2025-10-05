"""Tests for the Jackson Group scraper."""

from parser.scrapers.jacksongroup_scraper import (
    LISTINGS_URL,
    parse_appfolio_collection,
)


def test_parse_appfolio_collection_extracts_fields():
    payload = {
        "data": {
            "values": [
                {
                    "page_item_url": "e8080f5c-712e-4452-a83d-473ac72c05e4",
                    "data": {
                        "full_address": "1295 Union Street, San Francisco, CA 94109",
                        "bedrooms": 0,
                        "bathrooms": 1,
                        "market_rent": 1700,
                        "database_url": "https://jacksongroup.appfolio.com/",
                        "listable_uid": "e8080f5c-712e-4452-a83d-473ac72c05e4",
                        "rental_application_url": (
                            "https://jacksongroup.appfolio.com/listings/rental_applications/new"
                            "?listable_uid=e8080f5c-712e-4452-a83d-473ac72c05e4&source=Website"
                        ),
                    },
                }
            ]
        }
    }

    units = parse_appfolio_collection(payload, base_url=LISTINGS_URL)
    assert len(units) == 1
    unit = units[0]
    assert unit.address == "1295 Union Street, San Francisco, CA 94109"
    assert unit.bedrooms == 0
    assert unit.bathrooms == 1
    assert unit.rent == 1700
    assert unit.source_url == (
        "https://jacksongroup.appfolio.com/listings/detail/"
        "e8080f5c-712e-4452-a83d-473ac72c05e4"
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
