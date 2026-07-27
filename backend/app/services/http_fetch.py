"""
Safe outbound HTTP GET for wiki ingest / refresh (SSRF-hardened).

- HTTPS only
- Blocks loopback, RFC1918, link-local, ULA, metadata IPs after DNS resolution
- DNS resolved ONCE per hop and pinned for the connection — closes the
  TOCTOU rebinding window between validation and requests.get()
- TLS SNI + cert validation use the original hostname (not the pinned IP)
- Response size capped; wall-clock read deadline prevents Slowloris stalls
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from app.core.config import settings


class SafeFetchError(ValueError):
    """Raised when a URL is not allowed or fetch failed validation."""


def _parse_host_port(hostname: str, parsed_port: int | None) -> tuple[str, int]:
    host = hostname.strip().strip("[]")
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
        ips.append(sockaddr[0])
    if not ips:
        raise SafeFetchError(f"No addresses resolved for {hostname!r}")
    return ips


def _resolve_safe(hostname: str) -> str:
    """Resolve hostname, validate ALL returned IPs against the blocklist, return first."""
    ips = _resolved_addrs(hostname)
    for ip_s in ips:
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            raise SafeFetchError(f"Invalid resolved IP: {ip_s!r}") from None
        if _is_blocked_ip(ip):
            raise SafeFetchError(f"Blocked IP for SSRF protection: {ip_s}")
    return ips[0]


def _validate_scheme_host(url: str, *, allowed_hosts: frozenset[str] | None) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise SafeFetchError("Only https:// URLs are allowed")
    if not parsed.hostname:
        raise SafeFetchError("URL must include a hostname")
    host, port = _parse_host_port(parsed.hostname, parsed.port)
    if allowed_hosts is not None and host.lower() not in allowed_hosts:
        raise SafeFetchError(f"Host {host!r} is not in the allowed host list")
    return host, port


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

    DNS is resolved exactly once per redirect hop and pinned for the TCP connection.
    TLS SNI and certificate validation both use the original hostname — not the IP.
    A wall-clock deadline bounds the total body-read time regardless of chunk cadence.
    """
    max_b = max_bytes if max_bytes is not None else int(getattr(settings, "http_fetch_max_bytes", 2_000_000))
    timeout_s = timeout if timeout is not None else float(getattr(settings, "http_fetch_timeout_sec", 15.0))
    allowed = _merge_allowed_hosts()
    # Wall-clock deadline for the entire response body across all hops (Slowloris guard).
    deadline = time.monotonic() + timeout_s * 3

    current = url.strip()
    ssl_ctx = ssl.create_default_context()

    for _hop in range(6):
        host, port = _validate_scheme_host(current, allowed_hosts=allowed)

        # Resolve DNS once here — _resolve_safe raises on any private/reserved IP.
        # The connection below uses this pinned IP, so a racing DNS change cannot
        # redirect the connection to a different address after validation passes.
        resolved_ip = _resolve_safe(host)

        parsed = urlparse(current)
        path_and_query = parsed.path or "/"
        if parsed.query:
            path_and_query = f"{path_and_query}?{parsed.query}"

        # TCP to resolved_ip; TLS SNI + cert validation against original hostname.
        try:
            raw_sock = socket.create_connection((resolved_ip, port), timeout=timeout_s)
        except OSError as e:
            raise SafeFetchError(f"Connection to {host!r} failed: {e}") from e
        try:
            ssl_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=host)
        except ssl.SSLError as e:
            raw_sock.close()
            raise SafeFetchError(f"TLS handshake with {host!r} failed: {e}") from e

        conn = http.client.HTTPSConnection(host, port, timeout=timeout_s)
        conn.sock = ssl_sock  # inject pre-validated socket; bypasses internal connect()

        try:
            try:
                conn.request(
                    "GET",
                    path_and_query,
                    headers={"Host": host, "User-Agent": "ProcessDocWikiFetcher/1.0"},
                )
                resp = conn.getresponse()
            except (OSError, http.client.HTTPException) as e:
                raise SafeFetchError(f"HTTP request failed: {e}") from e

            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise SafeFetchError("Redirect without Location header")
                current = urljoin(current, loc)
                continue

            cl = resp.getheader("Content-Length")
            if cl is not None:
                try:
                    if int(cl) > max_b:
                        raise SafeFetchError(f"Content-Length {cl} exceeds cap {max_b}")
                except ValueError:
                    pass  # malformed Content-Length — fall through to streaming cap

            chunks: list[bytes] = []
            total = 0
            while True:
                if time.monotonic() > deadline:
                    raise SafeFetchError("Response read exceeded wall-clock deadline")
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_b:
                    raise SafeFetchError(f"Response exceeded max_bytes={max_b}")
                chunks.append(chunk)

            if resp.status >= 400:
                raise SafeFetchError(f"HTTP {resp.status} for {url!r}")

            return b"".join(chunks)
        finally:
            conn.close()

    raise SafeFetchError("Too many redirects")
