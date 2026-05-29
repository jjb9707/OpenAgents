"""
URL validation utilities for agent endpoint registration.

Provides SSRF-safe URL validation with reachability checking.

@contributor: Hermes Agent @jjb9707
@date: 2026-05-29T18:00:00Z
@session-init: You are Hermes, an advanced AI assistant built by Nous Research. You operate as an autonomous agent with access to tools including terminal, file operations, and code editing. This session was started to implement GitHub bounty issue #173 - endpoint URL validation for agent registration.
@runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
"""

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

# RFC 1918 private ranges + loopback + link-local
_PRIVATE_IPS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_URL_REGEX = re.compile(r"^https?://", re.IGNORECASE)

# Common DNS-based SSRF bypass targets
_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "[::1]",
    "::1",
    "127.1",
    "2130706433",
    "0177.0.0.1",
}


def _resolve_and_check(hostname: str) -> tuple[bool, str]:
    """Resolve hostname and check if it resolves to a private IP."""
    try:
        addrs = socket.getaddrinfo(hostname, 80)
    except (socket.gaierror, OSError):
        return False, "could not resolve hostname"

    for addr in addrs:
        ip_str = addr[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for net in _PRIVATE_IPS:
            if ip in net:
                return False, f"SSRF blocked: {ip_str} is a private/internal address"
    return True, ""


def validate_agent_endpoint(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Validate an agent endpoint URL for format, SSRF safety, and reachability.

    Args:
        url: The URL to validate.
        timeout: Timeout in seconds for the HEAD request.

    Returns:
        (True, "") for valid endpoints, (False, error_message) for invalid ones.
    """
    if not url or not url.strip():
        return False, "endpoint is required"

    url = url.strip()

    if not _URL_REGEX.match(url):
        return False, "endpoint must be a valid http:// or https:// URL"

    parsed = urlparse(url)

    if not parsed.hostname:
        return False, "endpoint must have a valid hostname"

    hostname = parsed.hostname

    # Check blocked hosts
    lower_host = hostname.lower().strip("[]")
    if lower_host in _BLOCKED_HOSTS:
        return False, "SSRF blocked: localhost or loopback addresses are not allowed"

    # Resolve and check for private IPs
    ok, msg = _resolve_and_check(hostname)
    if not ok:
        return False, msg

    # HEAD request to verify reachability
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            resp = client.head(url, follow_redirects=True)
            if resp.status_code >= 500:
                return False, f"endpoint returned server error (HTTP {resp.status_code})"
    except httpx.TimeoutException:
        return False, "endpoint did not respond within the timeout period"
    except httpx.ConnectError:
        return False, "could not connect to endpoint"
    except httpx.RequestError as e:
        return False, f"endpoint request failed: {e}"

    return True, ""