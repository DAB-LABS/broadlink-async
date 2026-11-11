"""RM Max local network discovery."""

from __future__ import annotations

import asyncio
import socket
import struct
import time

from .const import (
    DISCOVERY_ADDRESS,
    LAN_PROBE_REQUEST,
    LAN_PROBE_RESPONSE,
    NETWORK_HEADER_LENGTH,
    NETWORK_MAGIC,
    PROBE_BODY_LENGTH,
    RM_MAX_DEVTYPE,
)
from .models import DiscoveredRMMax

_CHECKSUM_OFFSET = 32
_DEVTYPE_OFFSET = 36
_MSGTYPE_OFFSET = 38
_SUBINDEX_OFFSET = 40


def checksum(data: bytes | bytearray) -> int:
    """Return the BroadLink LAN checksum."""
    return (0xBEAF + sum(data)) & 0xFFFF


def build_probe_request(subindex: int | None = None) -> bytes:
    """Build a BroadLink LAN probe request."""
    packet = bytearray(NETWORK_HEADER_LENGTH)
    struct.pack_into("<Q", packet, 0, NETWORK_MAGIC)
    struct.pack_into("<H", packet, _MSGTYPE_OFFSET, LAN_PROBE_REQUEST)
    if subindex is None:
        subindex = int(time.time() * 1000) | 0x8000
    struct.pack_into("<H", packet, _SUBINDEX_OFFSET, subindex & 0xFFFF)
    struct.pack_into("<H", packet, _CHECKSUM_OFFSET, checksum(packet))
    return bytes(packet)


def parse_probe_response(data: bytes, host: str) -> DiscoveredRMMax | None:
    """Parse an RM Max probe response."""
    if len(data) < NETWORK_HEADER_LENGTH + PROBE_BODY_LENGTH:
        return None
    if struct.unpack_from("<Q", data, 0)[0] != NETWORK_MAGIC:
        return None
    if struct.unpack_from("<H", data, _MSGTYPE_OFFSET)[0] != LAN_PROBE_RESPONSE:
        return None

    body_offset = NETWORK_HEADER_LENGTH
    devtype = struct.unpack_from("<H", data, body_offset + 4)[0]
    if devtype != RM_MAX_DEVTYPE:
        return None
    did = data[body_offset + 10 : body_offset + 16]
    mac = bytes(reversed(did)).hex()

    name = ""
    locked = False
    extension_offset = body_offset + PROBE_BODY_LENGTH
    if len(data) >= extension_offset + 64:
        name = (
            data[extension_offset : extension_offset + 62]
            .split(b"\0", 1)[0]
            .decode(errors="replace")
        )
        locked = bool(data[extension_offset + 63])
    return DiscoveredRMMax(
        host=host,
        mac=mac,
        devtype=devtype,
        name=name,
        locked=locked,
    )


def _discover_blocking(
    timeout: float,
    local_address: str,
    broadcast_address: tuple[str, int],
    stop_on_first: bool,
) -> list[DiscoveredRMMax]:
    devices: dict[str, DiscoveredRMMax] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((local_address, 0))
        sock.settimeout(min(timeout, 0.25))
        sock.sendto(build_probe_request(), broadcast_address)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(1460)
            except TimeoutError:
                continue
            if device := parse_probe_response(data, addr[0]):
                devices[device.mac] = device
                if stop_on_first:
                    break
    return list(devices.values())


async def discover_rmmax(
    timeout: float = 3.0,
    *,
    local_address: str = "0.0.0.0",
    broadcast_address: tuple[str, int] = DISCOVERY_ADDRESS,
    stop_on_first: bool = False,
) -> list[DiscoveredRMMax]:
    """Discover all RM Max gateways visible on a local interface."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    return await asyncio.to_thread(
        _discover_blocking,
        timeout,
        local_address,
        broadcast_address,
        stop_on_first,
    )
