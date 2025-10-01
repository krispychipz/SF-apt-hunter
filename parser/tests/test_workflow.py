from pathlib import Path

from parser.models import Site, Unit
from parser.workflow import WorkflowResult, collect_units_from_sites, filter_units


def make_unit(address, bedrooms, bathrooms, rent, neighborhood, url):
    return Unit(
        address=address,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        rent=rent,
        neighborhood=neighborhood,
        source_url=url,
    )


def test_filter_units_applies_criteria():
    units = [
        make_unit("A", 1, 1, 2500, "Mission", "http://example.com/1"),
        make_unit("B", 2, 1, 3200, "SOMA", "http://example.com/2"),
        make_unit("C", None, 1, 2800, "Mission", "http://example.com/3"),
        make_unit("D", 3, 2, None, "Noe Valley", "http://example.com/4"),
    ]

    filtered = filter_units(
        units,
        min_bedrooms=2,
        max_rent=3300,
        neighborhoods={"mission", "soma"},
    )

    assert [unit.address for unit in filtered] == ["B"]


def test_collect_units_from_sites_filters_and_deduplicates(tmp_path: Path, monkeypatch):
    sites = [
        Site(slug="site-a", url="https://example.com/a"),
        Site(slug="site-b", url="https://example.com/b"),
    ]

    units_by_url = {
        "https://example.com/a": [
            make_unit("111 Main", 2, 1, 3100, "Mission", "https://example.com/a"),
            make_unit("111 Main", 2, 1, 3100, "Mission", "https://example.com/a"),
        ],
        "https://example.com/b": [
            make_unit("222 Pine", 1, 1, 2400, "SOMA", "https://example.com/b"),
        ],
    }

    def fake_fetch(site: Site):
        html_path = tmp_path / f"{site.slug}.html"
        html_path.write_text("<html></html>")
        return "<html></html>", html_path

    def fake_extract(html: str, url: str):
        return units_by_url[url]

    monkeypatch.setitem(collect_units_from_sites.__globals__, "extract_units", fake_extract)

    result = collect_units_from_sites(
        sites,
        min_bedrooms=2,
        max_rent=3200,
        neighborhoods={"mission"},
        fetch_html=fake_fetch,
    )

    assert len(result.site_results) == 2
    assert all(res.html_path is not None for res in result.site_results if res.error is None)

    # One unit is filtered out for insufficient bedrooms, and duplicates are removed.
    aggregated = result.units
    assert len(aggregated) == 1
    assert aggregated[0].address == "111 Main"


def test_workflow_result_single_batch_wraps_units():
    units = [make_unit("X", 1, 1, 2000, "Mission", "https://example.com/x")]
    result = WorkflowResult.single_batch(units)
    assert result.units == units
    assert result.site_results[0].site.slug == "ad-hoc"
