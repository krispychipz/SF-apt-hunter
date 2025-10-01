"""Unit tests for text heuristics."""

from __future__ import annotations

import pytest

from parser.heuristics import (
    clean_neighborhood,
    looks_like_address,
    money_to_int,
    parse_bathrooms,
    parse_bedrooms,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$1,234", 1234),
        ("$2,100 per month", 2100),
        ("$3,200–$3,450", 3200),
        ("Call for pricing", None),
        ("No price", None),
    ],
)
def test_money_to_int(text: str, expected: int | None) -> None:
    assert money_to_int(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2 BR", 2.0),
        ("2br", 2.0),
        ("Studio", 0.0),
        ("Loft", None),
        ("No beds", None),
        ("3bd/2ba", 3.0),
    ],
)
def test_parse_bedrooms(text: str, expected: float | None) -> None:
    assert parse_bedrooms(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 bath", 1.0),
        ("1.5 BA", 1.5),
        ("2baths", 2.0),
        ("No baths", None),
    ],
)
def test_parse_bathrooms(text: str, expected: float | None) -> None:
    assert parse_bathrooms(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("123 Fake St, San Francisco", True),
        ("Unit 4B, 555 Market St", True),
        ("Contact us", False),
    ],
)
def test_looks_like_address(text: str, expected: bool) -> None:
    assert looks_like_address(text) is expected


def test_clean_neighborhood() -> None:
    assert clean_neighborhood("Hayes Valley, San Francisco, CA") == "Hayes Valley"
    assert clean_neighborhood("Mission District") == "Mission District"
