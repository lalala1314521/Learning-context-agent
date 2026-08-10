"""URL / 文件安全校验工具（SSRF 防护等）。"""

import ipaddress
from urllib.parse import urlparse


def is_internal_url(url: str) -> bool:
    """判断 URL 是否指向内网/本机地址（防止 SSRF）。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False
