"""Command line interface for SF Apt Hunter."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
import typer

from core.extract import extract_site, load_config
from core.util import render_email_summary, write_csv
from core.validate import NORMALIZED_FIELDS

app = typer.Typer(add_completion=False, help="Finder CLI")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

OUTPUT_DIR = Path("output")
FIXTURE_DIR = Path("fixtures")


def list_sites() -> list[str]:
    configs = Path("config/sites").glob("*.yml")
    return sorted(p.stem for p in configs)


@app.command()
def crawl(site: str = typer.Argument("all")) -> None:
    """Run extractor for one site or all sites."""
    sites = [site] if site != "all" else list_sites()
    if not sites:
        typer.echo("No sites configured.")
        raise typer.Exit(code=1)

    all_rows = []
    for target in sites:
        typer.echo(f"Running crawl for {target}")
        listings = extract_site(target)
        csv_path = OUTPUT_DIR / f"{target}-{datetime.utcnow().date().isoformat()}.csv"
        rows = []
        for listing in listings:
            record = listing.dict()
            record["scraped_at"] = listing.scraped_at.isoformat()
            rows.append(record)
        write_csv(csv_path, rows, NORMALIZED_FIELDS)
        all_rows.extend(rows)
        summary_rows = [
            row
            for row in rows
            if (row.get("beds") == 2 or row.get("beds") == 2.0)
            and (row.get("neighborhood") or "").lower() in {"hayes valley", "lower haight"}
        ]
        summary = render_email_summary(target, summary_rows)
        send_email(summary)

    typer.echo(f"Crawl complete. {len(all_rows)} listings across {len(sites)} sites.")


@app.command()
def check(site: str) -> None:
    """Run a fast canary on live seed and fixtures."""
    config = load_config(site)
    typer.echo(f"Checking site {site}")

    # Live check
    client = httpx.Client(follow_redirects=True, timeout=10.0)
    try:
        listings = extract_site(site, client=client)
    finally:
        client.close()

    passed_live = bool(listings)
    typer.echo(f"Live check: {'PASS' if passed_live else 'FAIL'} ({len(listings)} units)")

    # Fixture replay
    fixture_path = FIXTURE_DIR / site
    fixture_units = 0
    if fixture_path.exists():
        html_file = fixture_path / "sample.html"
        if html_file.exists():
            from core.extract import strategy_dom, strategy_jsonld

            html = html_file.read_text(encoding="utf-8")
            fixture_units += len(strategy_dom(config, html))
            seed = config.get("seeds", [""])[0]
            fixture_units += len(strategy_jsonld(config, seed, html))
        json_file = fixture_path / "sample.json"
        if json_file.exists():
            from core.extract import strategy_xhr

            data = json.loads(json_file.read_text(encoding="utf-8"))

            class StubClient:
                def get(self, url, *args, **kwargs):
                    class Resp:
                        status_code = 200

                        def __init__(self_inner, text=None):
                            self_inner._text = text or "User-agent: *\nAllow: /"

                        def raise_for_status(self_inner):
                            return None

                        @property
                        def text(self_inner):
                            return self_inner._text

                        def json(self_inner):
                            return data

                    if url.endswith("robots.txt"):
                        return Resp()
                    return Resp()

            fixture_units += len(strategy_xhr(config, config.get("seeds", [""])[0], StubClient()))
    typer.echo(f"Fixture check: {'PASS' if fixture_units else 'FAIL'} ({fixture_units} units)")

    if not (passed_live and fixture_units):
        typer.echo("Suggested YAML patch (review before applying):")
        typer.echo("---")
        typer.echo(f"# {site} selectors may be stale. Update field selectors or JSONPaths.")
        typer.echo("dom:")
        typer.echo("  field_selectors:")
        typer.echo("    title: REPLACE_WITH_NEW_SELECTOR")
        typer.echo("    rent: REPLACE_WITH_NEW_SELECTOR")
        typer.echo("---")


def send_email(body: str) -> None:
    """Placeholder email notifier that prints to stdout."""
    typer.echo("\n=== EMAIL PREVIEW ===")
    typer.echo(body)
    typer.echo("=== END EMAIL ===\n")


if __name__ == "__main__":
    app()
