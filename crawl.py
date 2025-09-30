# crawl.py
import asyncio
from typing import List
from fetch import Fetcher
from models import Listing
from criteria import matches
from notify import email_alert

# Adapters go here
from adapters.example_site import ExampleSite

async def run() -> None:
    found: List[Listing] = []
    fetch = Fetcher(concurrency=8, base_delay=0.6)
    adapters = [
        ExampleSite(fetch),
        # Add more: AnotherSite(fetch), ThirdSite(fetch)
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
