"""Brave Search via the Brave Web Search API. Free tier: 2,000 queries/month.

API docs: https://brave.com/search/api/
Endpoint: https://api.search.brave.com/res/v1/web/search
"""

from __future__ import annotations

import os

from .. import cache, http
from ..source_config import load
from ..result import Result

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
FREE_TIER_MONTHLY = 2000


class BraveSource:
    name = "brave"

    def __init__(self, retries: int = 2) -> None:
        self._session = http.get_session(retries=retries, backoff=1.0)
        self._ttl = load().cache_ttl_hours
        self._api_key = os.environ.get("BRAVE_API_KEY", "").strip()

    def search(self, query: str, n: int = 10) -> list[Result]:
        if not self._api_key:
            return []

        cached = cache.get(self.name, query, ttl_hours=self._ttl)
        if cached is not None:
            return [Result(**r) for r in cached]

        try:
            r = self._session.get(
                ENDPOINT,
                params={"q": query, "count": min(n, 10)},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._api_key,
                },
                timeout=http.DEFAULT_TIMEOUT,
            )
            if r.status_code == 401:
                print(
                    "[brave] 401 Unauthorized - check BRAVE_API_KEY. "
                    "Get a free key at https://brave.com/search/api/",
                    flush=True,
                )
                return []
            if r.status_code == 429:
                print("[brave] 429 Rate limited - free tier is 2,000 queries/month.", flush=True)
                return []
            if r.status_code != 200:
                return []

            data = r.json()
            results: list[Result] = []
            for item in data.get("web", {}).get("results", [])[:n]:
                results.append(Result(
                    source="brave",
                    title=item.get("title") or "",
                    url=item.get("url") or "",
                    snippet=item.get("description"),
                    extra={
                        "age": item.get("age"),
                        "language": item.get("language"),
                        "family_friendly": item.get("family_friendly"),
                    },
                ))
            cache.put(self.name, query, results)
            return results
        except Exception:
            return []


__all__ = ["BraveSource"]
