"""Tests for the core extraction flow."""

from __future__ import annotations

from parser.extract import extract_units


def test_extracts_multiple_units() -> None:
    html = """
    <html>
      <body>
        <div class="unit-card">
          <div class="price">$3,200 per month</div>
          <div class="meta">2 BR • 1.5 BA</div>
          <div class="address">123 Fake St, San Francisco, CA</div>
          <div class="neighborhood">Hayes Valley</div>
        </div>
        <div class="unit-card">
          <div class="rent">$4,500–$4,700</div>
          <div class="details">3 Beds / 2 Baths</div>
          <div class="location">456 Real Ave</div>
          <div class="area">Mission District</div>
        </div>
        <div class="unit-card">
          <div class="price">$2,100</div>
          <div class="meta">Studio • 1 BA</div>
          <div class="address">789 Sample Rd, San Francisco</div>
        </div>
      </body>
    </html>
    """

    units = extract_units(html, "https://example.com/listings")
    assert len(units) == 3

    first = units[0].to_dict()
    assert first["rent"] == 3200
    assert first["bedrooms"] == 2.0
    assert first["bathrooms"] == 1.5
    assert first["address"] == "123 Fake St, San Francisco, CA"
    assert first["neighborhood"] == "Hayes Valley"

    second = units[1].to_dict()
    assert second["rent"] == 4500
    assert second["bedrooms"] == 3.0
    assert second["bathrooms"] == 2.0
    assert second["address"] == "456 Real Ave"
    assert second["neighborhood"] == "Mission District"

    third = units[2].to_dict()
    assert third["bedrooms"] == 0.0
    assert third["rent"] == 2100


def test_deduplicates_units() -> None:
    html = """
    <div>
      <div class="card">
        <div class="price">$2,500</div>
        <div class="beds">2 BR</div>
        <div class="baths">1 BA</div>
        <div class="address">101 Main St</div>
      </div>
      <div class="card duplicate">
        <div class="price">$2,500</div>
        <div class="details">2 BR / 1 BA</div>
        <div class="address">101 Main St</div>
      </div>
    </div>
    """

    units = extract_units(html, "https://example.com/page")
    assert len(units) == 1
    unit = units[0].to_dict()
    assert unit["rent"] == 2500
    assert unit["bedrooms"] == 2.0
    assert unit["bathrooms"] == 1.0
