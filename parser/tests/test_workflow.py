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


def test_collect_units_from_sites_filters_and_deduplicates():
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

    scrapers = {
        "site-a": lambda url: units_by_url[url],
        "site-b": lambda url: units_by_url[url],
    }

    result = collect_units_from_sites(
        sites,
        min_bedrooms=2,
        max_rent=3200,
        neighborhoods={"mission"},
        scrapers=scrapers,
    )

    assert len(result.site_results) == 2
    assert all(res.error is None for res in result.site_results)

    # One unit is filtered out for insufficient bedrooms, and duplicates are removed.
    aggregated = result.units
    assert len(aggregated) == 1
    assert aggregated[0].address == "111 Main"


def test_collect_units_reports_missing_scraper():
    sites = [Site(slug="unknown", url="https://example.com")]

    result = collect_units_from_sites(sites, scrapers={})

    assert len(result.errors) == 1
    assert isinstance(result.errors[0].error, RuntimeError)


def test_collect_units_uses_scraper_default_url_when_missing():
    site = Site(slug="site-a", url="")

    def scraper():
        return [make_unit("333 Oak", 2, 1, 3100, None, "https://example.com/a")]

    result = collect_units_from_sites([site], scrapers={"site-a": scraper})

    assert len(result.site_results) == 1
    assert result.site_results[0].error is None
    assert [unit.address for unit in result.units] == ["333 Oak"]


def test_workflow_result_single_batch_wraps_units():
    units = [make_unit("X", 1, 1, 2000, "Mission", "https://example.com/x")]
    result = WorkflowResult.single_batch(units)
    assert result.units == units
    assert result.site_results[0].site.slug == "ad-hoc"
