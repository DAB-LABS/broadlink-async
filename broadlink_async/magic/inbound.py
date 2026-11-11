"""Industry-compatible inbound UDP gateway sessions."""

from __future__ import annotations

import asyncio
import logging
import struct
import uuid
from collections.abc import Callable

from .const import GATEWAY_LISTEN_PORT
from .models import normalize_mac

GATEWAY_SESSION_TIMEOUT = 180.0

MSG_DISCOVERY = 1
MSG_DISCOVERY_RESPONSE = 2
MSG_HEARTBEAT = 3
MSG_HEARTBEAT_RESPONSE = 4
MSG_CONTROL = 7
MSG_STATUS_UPLOAD = 15
MSG_STATUS_ACK = 16
MSG_STATUS_QUERY = 17
MSG_STATUS_QUERY_ACK = 18

_LOGGER = logging.getLogger(__name__)

PacketHandler = Callable[[bytes, tuple[str, int]], None]


def pack_message(message_type: int, sequence: int, payload: bytes = b"") -> bytes:
    """Pack one EasyIndustry UDP message."""
    return struct.pack("<HH", message_type, sequence) + payload


def unpack_header(data: bytes) -> tuple[int, int]:
    """Unpack and validate an EasyIndustry UDP header."""
    if len(data) < 4:
        raise ValueError("gateway packet is shorter than four bytes")
    return struct.unpack_from("<HH", data)


def gateway_mac_from_handshake(data: bytes) -> str | None:
    """Return the six-byte gateway MAC carried by discovery/heartbeat."""
    try:
        message_type, _sequence = unpack_header(data)
    except ValueError:
        return None
    if message_type not in (MSG_DISCOVERY, MSG_HEARTBEAT) or len(data) < 10:
        return None
    return normalize_mac(data[4:10].hex())


def parse_status_upload(data: bytes) -> list[tuple[int, bytes]]:
    """Extract short address and device payload from a type-15 upload."""
    message_type, _sequence = unpack_header(data)
    if message_type != MSG_STATUS_UPLOAD:
        return []
    payload = data[4:]
    reports: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(payload):
        segment_length = payload[offset]
        end = offset + segment_length + 1
        if segment_length == 0 or end > len(payload):
            break
        segment = payload[offset:end]
        if len(segment) >= 8 and segment[1] >> 4 == 0x0C:
            short_addr = ((segment[1] & 0x0F) << 8) | segment[5]
            reports.append((short_addr, bytes(segment[8:])))
        offset = end
    return reports


def pack_status_query(
    addresses: list[int],
    *,
    sequence: int,
    delay: int = 0,
) -> bytes:
    """Pack EasyIndustry's 16-byte device status query body."""
    if not addresses:
        addresses = [1]
    if not 0 <= delay <= 0xFF:
        raise ValueError("query delay must fit in uint8")
    if any(not 0 <= address <= 0xFFFF for address in addresses):
        raise ValueError("query address must fit in uint16")
    first = addresses[0]
    high = first >> 8
    low = first & 0xFF
    mask = bytearray(13)
    for address in addresses:
        if address >> 8 != high:
            raise ValueError("query addresses must share the same high byte")
        offset = (address & 0xFF) - low
        if not 0 <= offset < len(mask) * 8:
            raise ValueError("query addresses must fit in one 104-address window")
        mask[offset // 8] |= 1 << (offset % 8)
    return pack_message(
        MSG_STATUS_QUERY,
        sequence,
        bytes((delay, high, low)) + bytes(mask),
    )


class _InboundProtocol(asyncio.DatagramProtocol):
    """Forward every UDP datagram to the shared registry."""

    def __init__(self, registry: InboundGatewayRegistry) -> None:
        self.registry = registry

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.registry.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.registry.datagram_received(data, addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.warning("Gateway UDP listener error: %s", exc)


class InboundGatewayRegistry:
    """One fixed UDP listener shared by all imported families."""

    def __init__(
        self,
        *,
        local_mac: bytes | None = None,
        session_timeout: float = GATEWAY_SESSION_TIMEOUT,
    ) -> None:
        self.local_mac = local_mac or uuid.getnode().to_bytes(6, "big")
        self.session_timeout = session_timeout
        self.transport: asyncio.DatagramTransport | None = None
        self._handlers: dict[str, PacketHandler] = {}
        self._peers: dict[tuple[str, int], str] = {}

    async def async_start(
        self,
        host: str = "0.0.0.0",
        port: int = GATEWAY_LISTEN_PORT,
    ) -> None:
        """Bind the fixed listener once."""
        if self.transport is not None:
            return
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: _InboundProtocol(self),
            local_addr=(host, port),
        )

    def register(self, mac: str, handler: PacketHandler) -> None:
        """Register one imported gateway MAC."""
        self._handlers[normalize_mac(mac)] = handler

    def unregister(self, mac: str) -> None:
        """Unregister a gateway and forget its active peer."""
        normalized = normalize_mac(mac)
        self._handlers.pop(normalized, None)
        self._peers = {
            peer: peer_mac
            for peer, peer_mac in self._peers.items()
            if peer_mac != normalized
        }

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Route a packet by handshake MAC or previously learned peer."""
        try:
            message_type, sequence = unpack_header(data)
        except ValueError:
            _LOGGER.debug("Ignored short gateway packet from %s", addr)
            return
        mac = gateway_mac_from_handshake(data) or self._peers.get(addr)
        if mac is None:
            _LOGGER.debug("Ignored unregistered gateway packet from %s", addr)
            return
        handler = self._handlers.get(mac)
        if handler is None:
            _LOGGER.debug("Ignored gateway packet for unknown MAC %s", mac)
            return
        handshake_mac = gateway_mac_from_handshake(data)
        if handshake_mac is not None:
            self._peers = {
                peer: peer_mac
                for peer, peer_mac in self._peers.items()
                if peer_mac != mac or peer == addr
            }
        self._peers[addr] = mac
        handler(data, addr)
        if message_type == MSG_DISCOVERY:
            self.sendto(
                pack_message(MSG_DISCOVERY_RESPONSE, sequence, self.local_mac),
                addr,
            )
        elif message_type == MSG_HEARTBEAT:
            self.sendto(
                pack_message(MSG_HEARTBEAT_RESPONSE, sequence, self.local_mac),
                addr,
            )
        elif message_type == MSG_STATUS_UPLOAD and parse_status_upload(data):
            self.sendto(pack_message(MSG_STATUS_ACK, sequence), addr)

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        """Send through the shared listener socket."""
        if self.transport is None:
            raise RuntimeError("gateway UDP listener is not running")
        self.transport.sendto(data, addr)

    async def async_close(self) -> None:
        """Close the fixed listener."""
        if self.transport is not None:
            self.transport.close()
            self.transport = None
            await asyncio.sleep(0)
        self._peers.clear()
