from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.extract import (
    load_config,
    normalize_row,
    strategy_dom,
    strategy_jsonld,
    strategy_xhr,
    validate_row,
)


FIXTURES = Path("fixtures")


def test_rentsfnow_fixture():
    config = load_config("rentsfnow")
    html = (FIXTURES / "rentsfnow" / "sample.html").read_text(encoding="utf-8")
    units = strategy_jsonld(config, config.get("seeds", [""])[0], html)
    assert units, "jsonld should yield units"
    normalized = normalize_row("rentsfnow", units[0], config.get("seeds", [""])[0], config, 0)
    listing = validate_row(normalized)
    assert listing is not None
    assert listing.beds in (2, 2.0)
    assert listing.rent_min == 4200


def test_mosser_fixture_dom():
    config = load_config("mosser")
    html = (FIXTURES / "mosser" / "sample.html").read_text(encoding="utf-8")
    units = strategy_dom(config, html)
    assert units, "dom should yield units"
    normalized = normalize_row("mosser", units[0], config.get("seeds", [""])[0], config, 0)
    listing = validate_row(normalized)
    assert listing is not None
    assert listing.beds == 2


def test_mosser_fixture_xhr():
    config = load_config("mosser")
    data = (FIXTURES / "mosser" / "sample.json").read_text(encoding="utf-8")
    import json
    payload = json.loads(data)

    class FakeClient:
        def get(self, url, *args, **kwargs):
            class Response:
                status_code = 200

                def __init__(self_inner, text=None):
                    self_inner._text = text or "User-agent: *\nAllow: /"

                def raise_for_status(self_inner):
                    return None

                @property
                def text(self_inner):
                    return self_inner._text

                def json(self_inner):
                    return payload

            if url.endswith("robots.txt"):
                return Response()
            return Response()

    units = strategy_xhr(config, config.get("seeds", [""])[0], FakeClient())
    assert units
    normalized = normalize_row("mosser", units[0], config.get("seeds", [""])[0], config, 0)
    listing = validate_row(normalized)
    assert listing is not None
    assert listing.rent_min == 3995
