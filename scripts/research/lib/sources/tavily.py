"""Tavily Search via the Tavily API. Free tier: 1,000 queries/month.

API docs: https://docs.tavily.com/
Endpoint: https://api.tavily.com/search
"""

from __future__ import annotations

import os

from .. import cache, http
from ..source_config import load
from ..result import Result

ENDPOINT = "https://api.tavily.com/search"
FREE_TIER_MONTHLY = 1000


class TavilySource:
    name = "tavily"

    def __init__(self, retries: int = 2) -> None:
        self._session = http.get_session(retries=retries, backoff=1.0)
        self._ttl = load().cache_ttl_hours
        self._api_key = os.environ.get("TAVILY_API_KEY", "").strip()

    def search(self, query: str, n: int = 10) -> list[Result]:
        if not self._api_key:
            return []

        cached = cache.get(self.name, query, ttl_hours=self._ttl)
        if cached is not None:
            return [Result(**r) for r in cached]

        try:
            r = self._session.post(
                ENDPOINT,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": min(n, 10),
                    "include_answer": False,
                },
                headers={"Content-Type": "application/json"},
                timeout=http.DEFAULT_TIMEOUT,
            )
            if r.status_code == 401:
                print(
                    "[tavily] 401 Unauthorized - check TAVILY_API_KEY. "
                    "Get a free key at https://app.tavily.com/",
                    flush=True,
                )
                return []
            if r.status_code == 429:
                print("[tavily] 429 Rate limited - free tier is 1,000 queries/month.", flush=True)
                return []
            if r.status_code != 200:
                return []

            data = r.json()
            results: list[Result] = []
            for item in data.get("results", [])[:n]:
                results.append(Result(
                    source="tavily",
                    title=item.get("title") or "",
                    url=item.get("url") or "",
                    snippet=item.get("content"),
                    extra={
                        "score": item.get("score"),
                        "raw_content": bool(item.get("raw_content")),
                    },
                ))
            cache.put(self.name, query, results)
            return results
        except Exception:
            return []


__all__ = ["TavilySource"]
