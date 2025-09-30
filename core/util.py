"""Utility helpers for the extractor."""
from __future__ import annotations

import csv
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)


def stable_hash(parts: Iterable[str]) -> str:
    m = hashlib.sha256()
    for part in parts:
        if part:
            m.update(part.encode("utf-8"))
    return m.hexdigest()[:16]


def ensure_output_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_csv(path: str | os.PathLike[str], rows: Iterable[Mapping[str, object]], fieldnames: list[str]) -> None:
    ensure_output_dir(Path(path).parent)
    timestamp = datetime.utcnow().isoformat()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    logger.info("Wrote %s rows to %s at %s", count, path, timestamp)


def render_email_summary(site: str, rows: list[Mapping[str, object]]) -> str:
    lines = [f"Subject: SF Apt Hunter summary for {site}", ""]
    if not rows:
        lines.append("No 2BR listings in Hayes Valley or Lower Haight today.")
        return "\n".join(lines)
    lines.append("Listings:")
    for row in rows:
        lines.append(
            "- {title} | {neighborhood} | {beds}bd {baths}ba | ${rent_min}-{rent_max} | {url}".format(
                **{k: (row.get(k) or "?") for k in [
                    "title",
                    "neighborhood",
                    "beds",
                    "baths",
                    "rent_min",
                    "rent_max",
                    "url",
                ]}
            )
        )
    return "\n".join(lines)
