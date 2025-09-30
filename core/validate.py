"""Validation of normalized listings."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator

NORMALIZED_FIELDS = [
    "source",
    "scraped_at",
    "title",
    "address",
    "unit",
    "neighborhood",
    "beds",
    "baths",
    "sqft",
    "rent_min",
    "rent_max",
    "available_date",
    "url",
]


class Listing(BaseModel):
    source: str
    scraped_at: datetime
    title: Optional[str]
    address: Optional[str]
    unit: Optional[str]
    neighborhood: Optional[str]
    beds: Optional[float]
    baths: Optional[float]
    sqft: Optional[int]
    rent_min: Optional[int] = Field(ge=0)
    rent_max: Optional[int] = Field(ge=0)
    available_date: Optional[str]
    url: str

    @validator("rent_max")
    def ensure_max_gte_min(self, value):  # type: ignore[override]
        rent_min = getattr(self, "rent_min", None)
        if value is not None and rent_min is not None and value < rent_min:
            raise ValueError("rent_max must be >= rent_min")
        return value


__all__ = ["Listing", "NORMALIZED_FIELDS"]
