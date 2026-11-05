"""Who is calling: the one reader of ``X-Forwarded-For`` (T-5.5.8).

A caller can put anything in that header, so it means something only when a
proxy we trust wrote it. ``TRUSTED_PROXY_IPS`` names those proxies. Unset, the
header is ignored and the caller is the socket peer: until T-5.5.8 the rate
limiter and the audit log took the header's first entry from anyone, so a
client that sent a new value each time was never limited, and the audit log
recorded whatever address it chose.

With the peer trusted, the header is walked from the right, because each
proxy appends what it saw: the rightmost entries are the ones our own proxies
wrote and the leftmost is whatever the client sent. The first address that is
not a trusted proxy is the client. A malformed entry, before any such address,
means the header cannot be read: the caller is then the peer. So is a request
whose every hop is trusted, which came from inside. Some proxies append a port
(``1.2.3.4:5678``, ``[2001:db8::1]:443``), and such an entry reads as the
address it carries (T-5.5.9).

Everything that reports a caller's address goes through ``client_ip``: the
per-IP limits, the audit log, and the address stored on a session. Only the
limits go on to ``rate_limit_bucket``, which gives an IPv6 caller's whole /64
one bucket; the audit log and the session keep the full address.

An ASGI server can rewrite the peer before this runs: uvicorn's own proxy
handling is on by default for peers at 127.0.0.1, so the launchers pass
``--no-proxy-headers`` (README, "Running behind a reverse proxy").
"""
from __future__ import annotations

import ipaddress
import logging
import re
from functools import lru_cache
from typing import Iterable

from starlette.requests import HTTPConnection

from app.config import settings

logger = logging.getLogger(__name__)

_Address = ipaddress.IPv4Address | ipaddress.IPv6Address
_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# An address a proxy wrote with a port beside it. A bare IPv6 address has colons
# of its own, so only these two shapes say which part is the port.
_IPV4_WITH_PORT = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})")
_BRACKETED = re.compile(r"\[(.+)\](?::(\d{1,5}))?")
_MAX_PORT = 65535

# T-5.5.9: an IPv6 customer is routinely handed a whole /64, so one per address
# would give them 2**64 buckets.
_IPV6_BUCKET_PREFIX = 64


@lru_cache(maxsize=4)
def _parse_networks(raw: str) -> tuple[_Network, ...]:
    """``TRUSTED_PROXY_IPS`` as networks. A bad entry is logged and skipped,
    never fatal, and skipping one only ever trusts less."""
    networks: list[_Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_IPS: ignoring %r, which is neither an IP nor a CIDR", entry)
    return tuple(networks)


def _parse_address(value: str) -> _Address | None:
    """``value`` as an address, or None. A port beside it is dropped. An IPv4
    address carried as IPv6 (``::ffff:10.0.0.1``, what a dual-stack listener
    reports) is the IPv4 address, so it matches an IPv4 entry in the list."""
    text = value.strip()
    bracketed = _BRACKETED.fullmatch(text)
    with_port = bracketed or _IPV4_WITH_PORT.fullmatch(text)
    host, port = with_port.groups() if with_port else (text, None)
    if port is not None and int(port) > _MAX_PORT:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if bracketed and address.version != 6:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def _is_trusted(address: _Address, networks: Iterable[_Network]) -> bool:
    return any(address in network for network in networks)


def client_ip(connection: HTTPConnection) -> str | None:
    """The caller's address, or None when the request has no peer."""
    peer = connection.client.host if connection.client is not None else None
    networks = _parse_networks(settings.TRUSTED_PROXY_IPS or "")
    if peer is None or not networks:
        return peer
    peer_address = _parse_address(peer)
    if peer_address is None or not _is_trusted(peer_address, networks):
        return peer
    # Every line of the header, in order: a proxy may add a line of its own
    # rather than extend the client's, and the first line is then the client's.
    hops = ",".join(connection.headers.getlist("x-forwarded-for")).split(",")
    for hop in reversed(hops):
        address = _parse_address(hop)
        if address is None:
            return peer
        if not _is_trusted(address, networks):
            return str(address)
    return peer


def rate_limit_bucket(ip: str) -> str:
    """What the per-IP limits count ``ip`` under: its /64 for IPv6, the
    address itself for IPv4. Anything that is not an address (a test client's
    name, ``unknown``) is its own bucket."""
    address = _parse_address(ip)
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((int(address), _IPV6_BUCKET_PREFIX), strict=False))
    return str(address) if address is not None else ip
