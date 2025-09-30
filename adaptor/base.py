# adapters/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
from models import Listing

class SiteAdapter(ABC):
    name: str

    @abstractmethod
    async def listing_pages(self) -> list[str]:
        ...

    @abstractmethod
    async def parse_listing_page(self, url: str) -> AsyncIterator[Listing]:
        ...

    async def crawl(self) -> AsyncIterator[Listing]:
        for url in await self.listing_pages():
            async for item in self.parse_listing_page(url):
                yield item
