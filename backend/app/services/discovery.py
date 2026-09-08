from collections.abc import Callable

import httpx


class TavilyDiscovery:
    """Optional URL discovery; candidates become facts only after snapshot capture."""

    def __init__(self, api_key: str | None, post: Callable = httpx.post) -> None:
        self.api_key = api_key
        self.post = post

    def discover(self, query: str) -> list[str]:
        if not self.api_key:
            return []
        response = self.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": 5},
            timeout=15,
        )
        response.raise_for_status()
        return [
            item["url"]
            for item in response.json().get("results", [])
            if isinstance(item.get("url"), str)
        ]
