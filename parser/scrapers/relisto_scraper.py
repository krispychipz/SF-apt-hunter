from pathlib import Path
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional

from parser.models import Unit  # Make sure this import works in your environment

BASE_URL = "https://www.relisto.com/search/unfurnished/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

def clean_price(value: str):
    if value is None:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", value)
    if not m:
        return None
    s = m.group(0).replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        return None

def clean_float(value: str):
    if value is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", value)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None

def set_page_number(url: str, page: int) -> str:
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if page <= 1:
        qs.pop("sf_paged", None)
    else:
        qs["sf_paged"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

def get_page(url: str, session: requests.Session, timeout=20):
    resp = session.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def parse_listings(html: str, base_url: str = BASE_URL) -> List[Unit]:
    soup = BeautifulSoup(html, "lxml")
    listings = []
    for a in soup.select("a.listing-box"):
        href = a.get("href")
        url = href if href else None
        if url:
            url = requests.compat.urljoin(base_url, url)

        data_beds = a.get("data-beds")
        data_baths = a.get("data-baths")
        data_price = a.get("data-price")

        address = None
        loc = a.select_one("h4.location")
        if loc and loc.get_text(strip=True):
            address = loc.get_text(strip=True)
        if address is None and href and "/rentals/" in href:
            slug = href.rstrip("/").split("/")[-1]
            address = slug.replace("-", " ").title()

        beds = clean_float(data_beds) if data_beds else None
        if beds is None:
            beds_el = a.select_one(".item-beds .item-value")
            beds = clean_float(beds_el.get_text(strip=True)) if beds_el else None

        baths = clean_float(data_baths) if data_baths else None
        if baths is None:
            baths_el = a.select_one(".item-baths .item-value")
            baths = clean_float(baths_el.get_text(strip=True)) if baths_el else None

        price = clean_price(data_price) if data_price else None
        if price is None:
            price_el = a.select_one(".item-price .item-value")
            price = clean_price(price_el.get_text(strip=True)) if price_el else None

        if not address and not price and not url:
            continue

        listings.append(Unit(
            address=address,
            bedrooms=beds,
            bathrooms=baths,
            rent=price,
            neighborhood=None,
            source_url=url,
        ))
    return listings

def parse_relisto_listings(pages: int = 1, sleep: float = 1.0) -> List[Unit]:
    """Scrape Relisto unfurnished listings and return a list of Unit objects."""
    session = requests.Session()
    all_units: List[Unit] = []
    for page in range(1, max(1, pages) + 1):
        url = set_page_number(BASE_URL, page)
        try:
            html = get_page(url, session=session)
        except Exception:
            continue
        units = parse_listings(html, base_url=BASE_URL)
        if not units and page > 1:
            break
        all_units.extend(units)
        import time
        time.sleep(sleep)
    return all_units