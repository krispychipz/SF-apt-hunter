"""Tests for parsing site configuration YAML."""

from __future__ import annotations

import textwrap

import pytest

from parser.sites import load_sites_yaml, parse_sites_yaml


SAMPLE_YAML = textwrap.dedent(
    """
    # comment line
    sites:
      - slug: rentsfnow
        url: "https://www.rentsfnow.com/apartments/sf/"

      - slug: utopiamanagement
        url: "https://utopiamanagement.com/properties/rental-listings-san-francisco-bay-area-ca"  # trailing comment
    """
)


def test_parse_sites_yaml_extracts_sites():
    sites = parse_sites_yaml(SAMPLE_YAML)
    assert [site.slug for site in sites] == ["rentsfnow", "utopiamanagement"]
    assert sites[0].url == "https://www.rentsfnow.com/apartments/sf/"
    assert (
        sites[1].url
        == "https://utopiamanagement.com/properties/rental-listings-san-francisco-bay-area-ca"
    )


def test_parse_sites_yaml_rejects_missing_fields():
    malformed = "sites:\n  - slug: missing"
    with pytest.raises(ValueError):
        parse_sites_yaml(malformed)


def test_parse_sites_yaml_handles_full_sample():
    full_sample = textwrap.dedent(
        """
        sites:
          - slug: rentsfnow
            url: "https://www.rentsfnow.com/apartments/sf/"

          - slug: mosserliving
            url: "https://www.mosserliving.com/san-francisco-apartments/all/"

          - slug: jacksongroup
            url: "https://www.jacksongroup.net/find-a-home"

          - slug: gaetanirealestate
            url: "https://www.gaetanirealestate.com/vacancies"

          - slug: avalonhayesvalley
            url: "https://www.avaloncommunities.com/california/san-francisco-apartments/avalon-hayes-valley/"

          - slug: amsires
            url: "https://www.amsires.com/unfurnished-rental-listings"

          - slug: chandlerproperties
            url: "https://chandlerproperties.com/rental-listings/"

          - slug: anchorealtyinc
            url: "https://anchorealtyinc.com/residential-rentals/"

          - slug: veritasrent
            url: "https://www.veritasrent.com/floorplans.aspx"

          - slug: rentbt_searchlisting
            url: "https://properties.rentbt.com/searchlisting.aspx?ftst=&txtCity=san%20francisco&LocationGeoId=0&renewpg=1&LatLng=(37.7749295,-122.4194155)&"

          - slug: utopiamanagement
            url: "https://utopiamanagement.com/properties/rental-listings-san-francisco-bay-area-ca"  # potential listings page

          - slug: structureproperties
            url: "https://www.structureproperties.com/"  # roster of properties for rent

          - slug: reListo
            url: "https://www.relisto.com/search/unfurnished/"  # property management / leasing in SF
        """
    )

    sites = parse_sites_yaml(full_sample)

    assert len(sites) == 13
    assert sites[0].slug == "rentsfnow"
    assert sites[-1].slug == "reListo"


def test_parse_sites_yaml_rejects_duplicates():
    duplicated = textwrap.dedent(
        """
        sites:
          - slug: rentsfnow
            url: https://example.com/a
          - slug: rentsfnow
            url: https://example.com/b
        """
    )
    with pytest.raises(ValueError):
        parse_sites_yaml(duplicated)


def test_load_sites_yaml_reads_file(tmp_path):
    yaml_file = tmp_path / "sites.yaml"
    yaml_file.write_text(SAMPLE_YAML, encoding="utf-8")

    sites = load_sites_yaml(yaml_file)

    assert len(sites) == 2
    assert sites[0].to_dict() == {
        "slug": "rentsfnow",
        "url": "https://www.rentsfnow.com/apartments/sf/",
    }
