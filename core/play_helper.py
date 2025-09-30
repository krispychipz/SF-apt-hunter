"""Playwright helper for triage and discovery."""
from __future__ import annotations

from playwright.async_api import async_playwright


async def get_dom(url: str, wait_selector: str | None = None, collect_network: bool = True) -> tuple[str, list[dict]]:
    """Load a page once, capture HTML and optionally JSON network payloads."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        network_payloads: list[dict] = []

        if collect_network:
            async def handle_response(response):
                try:
                    if "application/json" in (response.headers.get("content-type") or ""):
                        data = await response.json()
                        network_payloads.append({
                            "url": response.url,
                            "status": response.status,
                            "json": data,
                        })
                except Exception:
                    return

            page.on("response", handle_response)

        await page.goto(url, wait_until="networkidle")
        if wait_selector:
            await page.wait_for_selector(wait_selector, timeout=10000)
        html = await page.content()
        await browser.close()
        return html, network_payloads
