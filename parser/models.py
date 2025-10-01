"""Data models for apartment unit extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(slots=True)
class Unit:
    """Representation of a single apartment unit listing."""

    address: Optional[str]
    bedrooms: Optional[float]
    bathrooms: Optional[float]
    rent: Optional[int]
    neighborhood: Optional[str]
    source_url: str

    def identity(self) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[int]]:
        """Return a tuple suitable for deduplication."""

        return (self.address, self.bedrooms, self.bathrooms, self.rent)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the unit to a JSON-serialisable dictionary."""

        return {
            "address": self.address,
            "bedrooms": float(self.bedrooms) if self.bedrooms is not None else None,
            "bathrooms": float(self.bathrooms) if self.bathrooms is not None else None,
            "rent": int(self.rent) if self.rent is not None else None,
            "neighborhood": self.neighborhood,
            "source_url": self.source_url,
        }

@dataclass(slots=True)
class Site:
    """Representation of a site that links to apartment listings."""

    slug: str
    url: str

    def to_dict(self) -> Dict[str, str]:
        """Return the site definition as a dictionary."""

        return {"slug": self.slug, "url": self.url}

