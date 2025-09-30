# crawl.py
import asyncio
from typing import List
from fetch import Fetcher
from models import Listing
from criteria import matches
from notify import email_alert

# Adapters go here
from adapters.rentsfnow import RentSFNowAdapter

async def run() -> None:
    found: List[Listing] = []
    fetch = Fetcher(concurrency=8, base_delay=0.6)
    adapters = [
        RentSFNowAdapter(fetch),
    ]
    try:
        for adapter in adapters:
            async for item in adapter.crawl():
                if matches(item):
                    found.append(item)
    finally:
        await fetch.close()

    email_alert(found)

if __name__ == "__main__":
    asyncio.run(run())
