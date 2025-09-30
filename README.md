# SF Apt Hunter

Minimal, configurable crawler that extracts San Francisco apartment listings from a curated list of property managers.

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # create this file with dependencies listed below
```

### Required Python Packages

- httpx
- pyyaml
- selectolax
- jsonpath-ng
- typer
- tenacity
- pydantic
- playwright (for discovery; optional at runtime)
- pytest (for tests)

Install Playwright browsers once via `playwright install chromium` when using the triage helper.

## Repository Layout

```
core/            # extractor, normalization, validation helpers
config/          # schema and per-site YAML configs
fixtures/        # stored HTML/JSON for regression tests
output/          # CSV outputs (created by CLI)
tests/           # canary tests
cli.py           # Typer-based CLI entry point
```

## Usage

### Crawl listings

Run for all sites:

```bash
python cli.py crawl all
```

Run for a single site:

```bash
python cli.py crawl rentsfnow
```

Outputs CSV files under `output/` and prints an email-ready summary for 2BR listings in Hayes Valley or Lower Haight.

### Check configuration health

```bash
python cli.py check rentsfnow
```

This command fetches live data, replays fixtures, and prints a minimal report. When a strategy fails, it prints a YAML patch stub that a reviewer can edit before committing.

### Triage with Playwright

Use `core.play_helper.get_dom` from an interactive session to capture HTML and network JSON when authoring or updating configs.

```python
import asyncio
from core.play_helper import get_dom
html, network = asyncio.run(get_dom("https://example.com/listings", wait_selector=".unit"))
```

## Adding a New Site

1. Copy `config/schema.yml` as a reference and create `config/sites/<site>.yml`.
2. Populate `seeds`, `strategy_order`, and the strategy sections (`jsonld`, `xhr`, `dom`). Prefer JSON-LD or XHR first.
3. Add any `hints` such as `neighborhood_from_seed` to ensure correct normalization.
4. Capture fixtures (`sample.html` and optional `sample.json`) under `fixtures/<site>/` for regression tests.
5. Update or add tests to cover the new fixture.
6. Run `pytest` and `python cli.py check <site>` to validate before deploying.

## Tests

Run the canary suite:

```bash
pytest
```

The tests replay the stored fixtures to ensure the extractor can still parse at least one unit with pricing data per site.

## Email Notifications

The CLI renders a text summary for qualifying 2BR units. SMTP hooks are placeholders; integrate with your preferred mail service if automation is required.
