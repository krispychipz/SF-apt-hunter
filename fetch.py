# fetch.py
import asyncio, random
import httpx
from tenacity import retry, wait_exponential_jitter, stop_after_attempt

DEFAULT_HEADERS = {
    "User-Agent": "AptFinder/0.1 (+contact: you@example.com)",
    "Accept-Language": "en-US,en;q=0.9",
}

class Fetcher:
    def __init__(self, timeout=30.0, concurrency=8, base_delay=0.6):
        self.client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout, http2=True)
        self.sem = asyncio.Semaphore(concurrency)
        self.base_delay = base_delay

    @retry(wait=wait_exponential_jitter(initial=1, max=8), stop=stop_after_attempt(4))
    async def _get_once(self, url: str) -> httpx.Response:
        resp = await self.client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp

    async def get(self, url: str) -> httpx.Response:
        async with self.sem:
            await asyncio.sleep(self.base_delay + random.random() * 0.5)
            return await self._get_once(url)

    async def close(self):
        await self.client.aclose()
