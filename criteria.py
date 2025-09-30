# criteria.py
from models import Listing

TARGET_NEIGHBORHOODS = [
    "hayes valley",
    "lower haight",
    "alamo square",
    "duboce triangle",
    "nopa",
]

def looks_like_target_area(l: Listing) -> bool:
    hay = " ".join(filter(None, [l.neighborhood_text, l.address, l.title])).lower()
    return any(tok in hay for tok in TARGET_NEIGHBORHOODS)

def matches(l: Listing) -> bool:
    # bedrooms >= 2 and in or near target neighborhoods
    if not l.bedrooms or l.bedrooms < 2.0:
        return False
    return looks_like_target_area(l)
