import json
import logging
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, AsyncIterator, Dict, Iterable, Iterator, List, Optional, Sequence, Set
from urllib.parse import urlencode, urljoin

from adapters.base import SiteAdapter
from fetch import Fetcher
from models import Listing

LOGGER = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(r"<script[^>]*id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", re.S)
_ASSIGNMENT_RES = [
    re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"rentpress_search_properties\s*=\s*(\{.*?\})\s*;", re.S),
    re.compile(r"rentpress_search_properties\s*=\s*(\[.*?\])\s*;", re.S),
]


@dataclass(frozen=True)
class _ListingCandidate:
    data: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None


class RentSFNowAdapter(SiteAdapter):
    """Adapter that scrapes the RentSFNow search site."""

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
        resp = await self.fetch.get(url)
        html = resp.text
        seen: Set[str] = set()

        blobs = self._extract_json_blobs(html)
        if not blobs:
            LOGGER.warning("%s: no structured data blobs found", self.name)
        for blob in blobs:
            for candidate in self._gather_candidates(blob):
                listing = self._candidate_to_listing(candidate)
                if listing is None:
                    continue
                if listing.source_url in seen:
                    continue
                seen.add(listing.source_url)
                yield listing

    # ------------------------------------------------------------------
    # Parsing helpers

    def _extract_json_blobs(self, html: str) -> List[Any]:
        blobs: List[Any] = []
        for match in _NEXT_DATA_RE.finditer(html):
            raw = unescape(match.group(1).strip())
            decoded = self._decode_json(raw)
            if decoded is not None:
                blobs.append(decoded)
        for pattern in _ASSIGNMENT_RES:
            for match in pattern.finditer(html):
                raw = unescape(match.group(1).strip())
                decoded = self._decode_json(raw)
                if decoded is not None:
                    blobs.append(decoded)
        return blobs

    def _decode_json(self, raw: str) -> Optional[Any]:
        raw = raw.strip()
        if raw.endswith("</script>"):
            raw = raw[: -len("</script>")]
        raw = raw.rstrip(";")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _gather_candidates(self, blob: Any) -> Iterator[_ListingCandidate]:
        property_context: Dict[str, Dict[str, Any]] = {}
        for node in self._walk(blob):
            if not isinstance(node, dict):
                continue
            typename = str(node.get("__typename", ""))
            slug = node.get("slug") or node.get("id")
            if typename.lower() in {"property", "building"} and slug:
                property_context[str(slug)] = node

        for node in self._walk(blob):
            if not isinstance(node, dict):
                continue
            if not self._looks_like_unit(node):
                continue
            context = None
            prop_ref = node.get("property") or node.get("propertyId") or node.get("property_id")
            if isinstance(prop_ref, dict):
                context = prop_ref
            elif prop_ref and str(prop_ref) in property_context:
                context = property_context[str(prop_ref)]
            yield _ListingCandidate(node, context)

    def _looks_like_unit(self, node: Dict[str, Any]) -> bool:
        keys = {k.lower() for k in node.keys()}
        has_bed = any(k in keys for k in ("bedrooms", "beds", "bed", "bedsmin", "bedsmax"))
        has_url = any(
            k in keys
            for k in ("url", "permalink", "availabilityurl", "availability_url", "canonicalurl", "floorplanurl", "availabilitypath", "link")
        )
        return has_bed and has_url

    def _candidate_to_listing(self, candidate: _ListingCandidate) -> Optional[Listing]:
        node = candidate.data
        context = candidate.context or {}

        url = self._pick_first((node, context), ("url", "permalink", "availabilityUrl", "availability_url", "canonicalUrl"))
        if not url:
            return None
        full_url = urljoin(self.BASE_URL, str(url))

        floorplan = self._pick_first((node,), ("name", "title", "floorplan", "floorplanName"))
        prop_name = self._pick_first((context, node), ("propertyName", "property", "buildingName"))
        title_parts = [part for part in (prop_name, floorplan) if part]
        title = " – ".join(map(str, title_parts)) if title_parts else "RentSFNow Listing"

        address = self._pick_first((node, context), ("address", "address1", "street", "fullAddress")) or ""
        neighborhood = self._pick_first((node, context), ("neighborhood", "neighborhoodName", "neighborhood_text"))
        if neighborhood not in (None, ""):
            neighborhood = str(neighborhood)
        else:
            neighborhood = None
        bedrooms = self._pick_first((node, context), ("bedrooms", "beds", "bed", "bedsMin", "beds_max"))
        bathrooms = self._pick_first((node, context), ("bathrooms", "baths", "bath", "bathsMin", "baths_max"))
        rent = self._pick_first(
            (node, context),
            ("rent", "price", "minRent", "maxRent", "marketRent", "effectiveRent", "monthlyRent"),
        )
        photos = self._extract_photos(node, context)

        try:
            listing = Listing(
                source=self.name,
                source_url=full_url,
                title=str(title),
                address=str(address),
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                rent_monthly_usd=rent,
                neighborhood_text=neighborhood,
                photos=photos,
            )
        except Exception as exc:  # pragma: no cover - validation fallback
            LOGGER.debug("%s: failed to build Listing for %s (%s)", self.name, full_url, exc)
            return None

        if listing.bedrooms and listing.bedrooms < self.min_bedrooms:
            return None
        return listing

    def _extract_photos(self, *dicts: Dict[str, Any]) -> List[str]:
        photos: List[str] = []
        for d in dicts:
            if not isinstance(d, dict):
                continue
            for key in ("photos", "images", "gallery", "media"):
                value = d.get(key)
                if not value:
                    continue
                photos.extend(self._normalize_photos(value))
        deduped: List[str] = []
        seen: Set[str] = set()
        for url in photos:
            if isinstance(url, str) and url.startswith("http") and url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    def _normalize_photos(self, value: Any) -> List[str]:
        urls: List[str] = []
        if isinstance(value, str):
            if value.startswith("http"):
                urls.append(value)
        elif isinstance(value, dict):
            for key in ("url", "src", "image", "href"):
                maybe = value.get(key)
                if isinstance(maybe, str) and maybe.startswith("http"):
                    urls.append(maybe)
        elif isinstance(value, list):
            for item in value:
                urls.extend(self._normalize_photos(item))
        return urls

    def _pick_first(self, sources: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Optional[Any]:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                value = source.get(key)
                if value in (None, ""):
                    continue
                cleaned = self._clean_value(value)
                if cleaned not in (None, ""):
                    return cleaned
        return None

    def _clean_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("value", "text", "name", "title", "label", "display", "line1", "line_1", "address1", "addressLine1"):
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

