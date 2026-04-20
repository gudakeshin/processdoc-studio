"""
Safe outbound HTTP GET for wiki ingest / refresh (SSRF-hardened).

- HTTPS only (configurable)
- Blocks loopback, RFC1918, link-local, ULA, metadata IPs after DNS resolution
- Re-validates redirect targets (DNS + scheme) to mitigate rebinding
- TLS verification always on; response size capped
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from app.core.config import settings


class SafeFetchError(ValueError):
    """Raised when a URL is not allowed or fetch failed validation."""


def _parse_host_port(hostname: str, parsed_port: int | None) -> tuple[str, int]:
    host = hostname.strip().strip("[]")
    if host.startswith("xn--"):
        pass
    port = parsed_port if parsed_port is not None else 443
    return host, port


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    # Unique local for IPv6 (fc00::/7)
    return ip.version == 6 and int(ip) & (0xFE << 120) == (0xFC << 120)


def _resolved_addrs(hostname: str) -> list[str]:
    """Return all resolved IP strings for hostname (IPv4 + IPv6)."""
    infos: list[tuple[Any, ...]] = []
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as e:
        raise SafeFetchError(f"DNS resolution failed for {hostname!r}: {e}") from e
    ips: list[str] = []
    for _fam, _typ, _proto, _canon, sockaddr in infos:
        ip_s = sockaddr[0]
        ips.append(ip_s)
    if not ips:
        raise SafeFetchError(f"No addresses resolved for {hostname!r}")
    return ips


def _validate_host_before_connect(hostname: str) -> None:
    for ip_s in _resolved_addrs(hostname):
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            raise SafeFetchError(f"Invalid resolved IP: {ip_s!r}") from None
        if _is_blocked_ip(ip):
            raise SafeFetchError(f"Blocked IP for SSRF protection: {ip_s}")


def _validate_url(url: str, *, allowed_hosts: frozenset[str] | None) -> tuple[str, str, int]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise SafeFetchError("Only https:// URLs are allowed")
    if not parsed.hostname:
        raise SafeFetchError("URL must include a hostname")
    host, port = _parse_host_port(parsed.hostname, parsed.port)
    if allowed_hosts is not None and host.lower() not in allowed_hosts:
        raise SafeFetchError(f"Host {host!r} is not in the allowed host list")
    _validate_host_before_connect(host)
    return url, host, port


def _merge_allowed_hosts() -> frozenset[str] | None:
    raw = (getattr(settings, "http_fetch_allowed_hosts", None) or "").strip()
    if not raw:
        return None
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def safe_get(
    url: str,
    *,
    max_bytes: int | None = None,
    timeout: float | None = None,
) -> bytes:
    """
    Perform a validated HTTPS GET and return response body bytes (capped), or raise SafeFetchError.
    """
    max_b = max_bytes if max_bytes is not None else int(getattr(settings, "http_fetch_max_bytes", 2_000_000))
    timeout_s = timeout if timeout is not None else float(getattr(settings, "http_fetch_timeout_sec", 15.0))
    allowed = _merge_allowed_hosts()

    current = url.strip()
    _validate_url(current, allowed_hosts=allowed)

    session = requests.Session()
    session.max_redirects = 5

    for _hop in range(6):
        parsed = urlparse(current)
        host, _port = _parse_host_port(parsed.hostname or "", parsed.port)
        _validate_url(current, allowed_hosts=allowed)

        try:
            resp = session.get(
                current,
                timeout=timeout_s,
                verify=True,
                stream=True,
                allow_redirects=False,
                headers={"User-Agent": "ProcessDocWikiFetcher/1.0"},
            )
        except requests.RequestException as e:
            raise SafeFetchError(f"HTTP request failed: {e}") from e

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                resp.close()
                raise SafeFetchError("Redirect without Location header")
            resp.close()
            current = urljoin(current, loc)
            continue

        cl = resp.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > max_b:
                    resp.close()
                    raise SafeFetchError(f"Content-Length {cl} exceeds cap {max_b}")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_b:
                    raise SafeFetchError(f"Response exceeded max_bytes={max_b}")
                chunks.append(chunk)
        finally:
            resp.close()

        if not resp.ok:
            raise SafeFetchError(f"HTTP {resp.status_code} for {url!r}")

        return b"".join(chunks)

    raise SafeFetchError("Too many redirects")
