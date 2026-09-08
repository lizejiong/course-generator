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
        raise ValueError("只允许不含认证信息的 HTTP(S) URL")
    addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    for _, _, _, _, endpoint in addresses:
        address = ipaddress.ip_address(endpoint[0])
        if not address.is_global:
            raise ValueError("禁止访问本机、内网和保留网络地址")
    return value


def fetch_source(url: str, max_bytes: int = 2_000_000) -> SourceSnapshot:
    import hashlib

    validated = validate_public_http_url(url)
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        response = client.get(validated)
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("来源响应超过大小限制")
    extracted = trafilatura.extract(response.text) or ""
    if not extracted.strip():
        raise ValueError("来源页面没有可提取的正文")
    return SourceSnapshot(validated, extracted, hashlib.sha256(extracted.encode()).hexdigest())
