import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura


@dataclass(frozen=True)
class SourceSnapshot:
    url: str
    content: str
    sha256: str


def validate_public_http_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("only plain HTTP(S) URLs are allowed")
    addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    for _, _, _, _, endpoint in addresses:
        address = ipaddress.ip_address(endpoint[0])
        if not address.is_global:
            raise ValueError("local, private, and reserved network addresses are forbidden")
    return value


def fetch_source(url: str, max_bytes: int = 2_000_000) -> SourceSnapshot:
    import hashlib

    validated = validate_public_http_url(url)
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        response = client.get(validated)
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("source response exceeded the size limit")
    extracted = trafilatura.extract(response.text) or ""
    if not extracted.strip():
        raise ValueError("source did not contain extractable text")
    return SourceSnapshot(validated, extracted, hashlib.sha256(extracted.encode()).hexdigest())
