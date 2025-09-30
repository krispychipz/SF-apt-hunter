# models.py
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, validator

class Listing(BaseModel):
    source: str
    source_url: HttpUrl
    title: str
    address: str
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    rent_monthly_usd: Optional[int] = None
    neighborhood_text: Optional[str] = None
    photos: List[HttpUrl] = Field(default_factory=list)

    @validator("bedrooms", "bathrooms", pre=True)
    def coerce_float(cls, v):
        if v is None:
            return v
        try:
            return float(str(v).strip().split()[0].replace("+", ""))
        except Exception:
            return None

    @validator("rent_monthly_usd", pre=True)
    def coerce_int(cls, v):
        if v is None:
            return None
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return int(digits) if digits else None
