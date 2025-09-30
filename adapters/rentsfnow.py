import json
import logging
import re
from typing import Any, AsyncIterator, Dict, Iterable, Iterator, List, Optional, Sequence
from urllib.parse import urlencode, urljoin

from adapters.base import SiteAdapter
from fetch import Fetcher
from models import Listing

LOGGER = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(r"<script[^>]*id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", re.S)
_ASSIGNMENT_RES = [
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"rentpress_search_properties\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"rentpress_search_properties\s*=\s*(\[.*?\])\s*;", re.S),
]


class RentSFNowAdapter(SiteAdapter):
    """Adapter that scrapes basic unit info from RentSFNow."""

    name = "RentSFNow"
    BASE_URL = "https://www.rentsfnow.com"
    SEARCH_PATH = "/search/"

    def __init__(
        self,
        fetch: Fetcher,
        *,
        min_bedrooms: int = 2,
        neighborhoods: Optional[Iterable[str]] = None,
    ) -> None:
        self.fetch = fetch
        self.min_bedrooms = min_bedrooms
        if neighborhoods is None:
            neighborhoods = (
                "Hayes Valley",
                "Lower Haight",
                "Alamo Square",
                "Duboce Triangle",
                "NoPa",
            )
        self.target_neighborhoods = list(neighborhoods)

    async def listing_pages(self) -> List[str]:
        params: Dict[str, Any] = {
            "property-type": "apartments",
            "bedrooms": str(self.min_bedrooms),
        }
        if self.target_neighborhoods:
            params["neighborhood[]"] = self.target_neighborhoods
        query = urlencode(params, doseq=True)
        return [f"{self.BASE_URL}{self.SEARCH_PATH}?{query}"]

    async def parse_listing_page(self, url: str) -> AsyncIterator[Listing]:
        response = await self.fetch.get(url)
        seen_urls: set[str] = set()

        for payload in self._extract_payloads(response.text):
            for unit, context in self._iter_units(payload):
                listing = self._build_listing(unit, context)
                if listing is None:
                    continue
                if listing.source_url in seen_urls:
                    continue
                seen_urls.add(listing.source_url)
                if listing.bedrooms and listing.bedrooms < self.min_bedrooms:
                    continue
                yield listing

    # ------------------------------------------------------------------
    # Helpers

    def _extract_payloads(self, html: str) -> List[Any]:
        blobs: List[Any] = []
        for match in _NEXT_DATA_RE.finditer(html):
            decoded = self._decode_json(match.group(1))
            if decoded is not None:
                blobs.append(decoded)
        for pattern in _ASSIGNMENT_RES:
            for match in pattern.finditer(html):
                decoded = self._decode_json(match.group(1))
                if decoded is not None:
                    blobs.append(decoded)
        if not blobs:
            LOGGER.warning("%s: could not find structured payloads", self.name)
        return blobs

    def _decode_json(self, raw: str) -> Optional[Any]:
        cleaned = raw.strip().rstrip("</script>").rstrip(";")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            LOGGER.debug("%s: failed to decode payload", self.name)
            return None

    def _iter_units(self, payload: Any) -> Iterator[tuple[Dict[str, Any], Dict[str, Any]]]:
        property_map: Dict[str, Dict[str, Any]] = {}
        for node in self._walk(payload):
            if not isinstance(node, dict):
                continue
            slug = node.get("slug") or node.get("id") or node.get("propertyId")
            if not slug:
                continue
            if any(key in node for key in ("neighborhood", "neighborhoodName", "address")):
                property_map[str(slug)] = node

        for node in self._walk(payload):
            if not isinstance(node, dict):
                continue
            if not self._looks_like_unit(node):
                continue
            context: Dict[str, Any] = {}
            prop_ref = node.get("property") or node.get("propertyId") or node.get("property_id")
            if isinstance(prop_ref, dict):
                context = prop_ref
            elif prop_ref and str(prop_ref) in property_map:
                context = property_map[str(prop_ref)]
            yield node, context

    def _looks_like_unit(self, node: Dict[str, Any]) -> bool:
        bedrooms = self._first_value((node,), ("bedrooms", "beds", "bedsMin", "bedsMax"))
        url = self._first_value(
            (node,),
            (
                "url",
                "permalink",
                "availabilityUrl",
                "availability_url",
                "canonicalUrl",
                "floorPlanUrl",
            ),
        )
        return bedrooms is not None and bool(url)

    def _build_listing(self, unit: Dict[str, Any], context: Dict[str, Any]) -> Optional[Listing]:
        url = self._first_value(
            (unit, context),
            (
                "url",
                "permalink",
                "availabilityUrl",
                "availability_url",
                "canonicalUrl",
            ),
        )
        if not url:
            return None
        full_url = urljoin(self.BASE_URL, str(url))

        floorplan = self._first_value((unit,), ("name", "title", "floorplan", "floorplanName"))
        property_name = self._first_value((context, unit), ("propertyName", "property", "buildingName"))
        title_parts = [part for part in (property_name, floorplan) if part]
        title = " – ".join(map(str, title_parts)) if title_parts else "RentSFNow Listing"

        address = self._first_value((unit, context), ("address", "address1", "street", "fullAddress")) or ""
        neighborhood = self._first_value(
            (unit, context),
            ("neighborhood", "neighborhoodName", "neighborhood_text"),
        )

        bedrooms = self._first_value((unit,), ("bedrooms", "beds", "bedsMin", "bedsMax"))
        bathrooms = self._first_value((unit,), ("bathrooms", "baths", "bathsMin", "bathsMax"))
        rent = self._first_value(
            (unit,),
            ("rent", "price", "minRent", "maxRent", "marketRent", "effectiveRent", "monthlyRent"),
        )

        try:
            return Listing(
                source=self.name,
                source_url=full_url,
                title=str(title),
                address=str(address),
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                rent_monthly_usd=rent,
                neighborhood_text=str(neighborhood) if neighborhood else None,
            )
        except Exception as exc:  # pragma: no cover - validation fallback
            LOGGER.debug("%s: failed to build listing for %s (%s)", self.name, full_url, exc)
            return None

    def _first_value(self, sources: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Optional[Any]:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                if key not in source:
                    continue
                value = source.get(key)
                cleaned = self._clean_value(value)
                if cleaned not in (None, ""):
                    return cleaned
        return None

    def _clean_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("value", "text", "name", "title", "label", "display"):
                if key in value and value[key] not in (None, ""):
                    return value[key]
            return None
        if isinstance(value, (list, tuple)):
            for item in value:
                cleaned = self._clean_value(item)
                if cleaned not in (None, ""):
                    return cleaned
            return None
        return value

    def _walk(self, value: Any) -> Iterator[Any]:
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from self._walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from self._walk(item)
