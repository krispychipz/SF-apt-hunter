"""Minimal httpx-compatible shim for offline testing."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Optional


class HTTPError(Exception):
    pass


class HTTPStatusError(HTTPError):
    def __init__(self, message: str, status_code: int, request_url: str):
        super().__init__(message)
        self.response = SimpleNamespace(status_code=status_code, url=request_url)


@dataclass
class Response:
    status_code: int
    content: bytes
    url: str
    headers: Dict[str, str]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code} for {self.url}", self.status_code, self.url)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class Client:
    def __init__(self, follow_redirects: bool = True, timeout: Optional[float] = None):
        self.follow_redirects = follow_redirects
        self.timeout = timeout

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout or 10.0) as resp:
                content = resp.read()
                headers_dict = {k.lower(): v for k, v in resp.headers.items()}
                return Response(status_code=resp.status, content=content, url=resp.geturl(), headers=headers_dict)
        except urllib.error.HTTPError as exc:
            content = exc.read() if hasattr(exc, "read") else b""
            headers_dict = dict(exc.headers.items()) if exc.headers else {}
            raise HTTPStatusError(str(exc), exc.code, url) from None
        except urllib.error.URLError as exc:
            raise HTTPError(str(exc)) from None

    def close(self) -> None:
        return None


class AsyncClient:
    def __init__(self, *args, **kwargs):  # pragma: no cover - stub
        raise NotImplementedError("AsyncClient is not implemented in this shim")


__all__ = [
    "Client",
    "Response",
    "HTTPError",
    "HTTPStatusError",
]
