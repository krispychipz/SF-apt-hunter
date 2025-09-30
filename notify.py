"""Notification helpers."""
from typing import Iterable
from models import Listing

def email_alert(listings: Iterable[Listing]) -> None:
    # Placeholder implementation. Wire this up to an email provider later.
    items = list(listings)
    print(f"Found {len(items)} matching listings")
