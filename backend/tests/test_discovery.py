from app.services.discovery import TavilyDiscovery


class Response:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"results": [{"url": "https://example.com"}, {"title": "missing URL"}]}


def test_discovery_is_disabled_without_key_and_returns_only_urls_with_key() -> None:
    assert TavilyDiscovery(None).discover("ignored") == []
    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    assert TavilyDiscovery("key", post).discover("course topic") == ["https://example.com"]
    assert calls[0][1]["json"]["query"] == "course topic"
