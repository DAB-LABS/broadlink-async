"""RM Max gateway registry and multi-gateway fan-out."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .fastcon import apply_family_token, device_control, scene_control
from .inbound import (
    GATEWAY_SESSION_TIMEOUT,
    MSG_CONTROL,
    MSG_DISCOVERY,
    MSG_HEARTBEAT,
    MSG_STATUS_QUERY_ACK,
    MSG_STATUS_UPLOAD,
    pack_message,
    pack_status_query,
    parse_status_upload,
    unpack_header,
)
from .models import DiscoveredRMMax, Family, normalize_mac

DatagramSender = Callable[[bytes, tuple[str, int]], None]
ReportCallback = Callable[[int, bytes], None]
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GatewayState:
    """Runtime state for one RM Max."""

    mac: str
    host: str
    port: int = 0
    name: str = ""
    online: bool = False
    peer: tuple[str, int] | None = None
    last_seen: float = 0.0


class GatewaySet:
    """All RM Max gateways currently associated with one family."""

    def __init__(
        self,
        family: Family,
        gateways: Iterable[DiscoveredRMMax] = (),
        *,
        sender: DatagramSender | None = None,
        report_callback: ReportCallback | None = None,
    ) -> None:
        self.family = family
        self._sender = sender
        self._report_callback = report_callback
        self._gateways: dict[str, GatewayState] = {}
        self._fastcon_seq = 0
        self._gateway_seq = 0
        for device in self.family.gateways:
            mac = normalize_mac(device.mac or device.did)
            if mac:
                self._gateways[mac] = GatewayState(
                    mac=mac,
                    host="",
                    name=device.name,
                )
        self.update_discovered(gateways)

    @property
    def gateways(self) -> tuple[GatewayState, ...]:
        """Return all matched gateway states."""
        return tuple(self._gateways.values())

    @property
    def online_gateways(self) -> tuple[GatewayState, ...]:
        """Return all online gateways."""
        self.expire_sessions()
        return tuple(
            gateway
            for gateway in self._gateways.values()
            if gateway.online and gateway.peer is not None
        )

    def set_report_callback(self, callback: ReportCallback) -> None:
        """Set the callback for decrypted FastCon reports."""
        self._report_callback = callback

    def update_discovered(self, devices: Iterable[DiscoveredRMMax]) -> None:
        """Reconcile LAN discovery results with imported RM Max devices."""
        expected = {
            normalize_mac(device.mac or device.did)
            for device in self.family.gateways
            if normalize_mac(device.mac or device.did)
        }
        for device in devices:
            mac = normalize_mac(device.mac)
            if expected and mac not in expected:
                continue
            state = self._gateways.get(mac)
            if state is None:
                self._gateways[mac] = GatewayState(
                    mac=mac,
                    host=device.host,
                    port=device.port,
                    name=device.name,
                )
            else:
                state.host = device.host
                state.port = device.port
                state.name = device.name or state.name

    def _next_fastcon_seq(self) -> int:
        self._fastcon_seq = (self._fastcon_seq % 0xFF) + 1
        return self._fastcon_seq

    def _next_gateway_seq(self) -> int:
        self._gateway_seq = (self._gateway_seq + 1) & 0xFFFF
        return self._gateway_seq

    def handle_packet(
        self,
        mac: str,
        data: bytes,
        addr: tuple[str, int],
    ) -> None:
        """Update one inbound gateway session and dispatch status reports."""
        gateway = self._gateways.get(normalize_mac(mac))
        if gateway is None:
            return
        try:
            message_type, _sequence = unpack_header(data)
        except ValueError:
            return
        if message_type not in (
            MSG_DISCOVERY,
            MSG_HEARTBEAT,
            MSG_STATUS_UPLOAD,
            MSG_STATUS_QUERY_ACK,
        ):
            return
        session_changed = not gateway.online or gateway.peer != addr
        gateway.host = addr[0]
        gateway.port = addr[1]
        gateway.peer = addr
        gateway.online = True
        gateway.last_seen = time.monotonic()
        if session_changed:
            _LOGGER.debug(
                "Gateway inbound session online gateway=%s peer=%s",
                gateway.mac,
                addr,
            )
        if message_type == MSG_STATUS_UPLOAD and self._report_callback is not None:
            for short_addr, payload in parse_status_upload(data):
                _LOGGER.debug(
                    "Received Bluetooth status gateway=%s peer=%s "
                    "short_addr=%s payload=%s",
                    gateway.mac,
                    addr,
                    short_addr,
                    payload.hex(),
                )
                self._report_callback(short_addr, payload)
        elif message_type == MSG_STATUS_QUERY_ACK:
            _LOGGER.debug(
                "Received status query ACK gateway=%s peer=%s sequence=%s",
                gateway.mac,
                addr,
                _sequence,
            )

    def expire_sessions(self, now: float | None = None) -> None:
        """Mark sessions offline after the Industry heartbeat timeout."""
        current = time.monotonic() if now is None else now
        for gateway in self._gateways.values():
            if (
                gateway.online
                and gateway.last_seen
                and current - gateway.last_seen >= GATEWAY_SESSION_TIMEOUT
            ):
                gateway.online = False
                gateway.peer = None

    async def async_close(self) -> None:
        """Forget runtime sessions without owning the shared listener."""
        for gateway in self._gateways.values():
            gateway.online = False
            gateway.peer = None

    async def _async_send_fastcon(self, frame: bytes) -> int:
        """Wrap and fan out one FastCon frame through active inbound sessions."""
        gateways = list(self.online_gateways)
        if not gateways:
            return 0
        _LOGGER.debug(
            "Sending Bluetooth FastCon frame gateways=%s frame=%s",
            [gateway.mac for gateway in gateways],
            frame.hex(),
        )
        if self._sender is None:
            return 0
        successful = 0
        for gateway in gateways:
            assert gateway.peer is not None
            self._sender(
                pack_message(MSG_CONTROL, self._next_gateway_seq(), frame),
                gateway.peer,
            )
            successful += 1
        return successful

    async def send_remote_payloads(
        self,
        short_addr: int,
        payloads: Iterable[bytes],
    ) -> int:
        """Encode and fan out remote payloads to every online RM Max."""
        sent = 0
        source_addr = bytes.fromhex(self.family.bletoken)[-1]
        for payload in payloads:
            frame = device_control(
                short_addr,
                payload,
                seq=self._next_fastcon_seq(),
                source_addr=source_addr,
            )
            frame = apply_family_token(frame, self.family.bletoken)
            sent += await self._async_send_fastcon(frame)
        return sent

    async def send_scene(self, scene_id: int) -> int:
        """Activate a stored scene on every online RM Max."""
        source_addr = bytes.fromhex(self.family.bletoken)[-1]
        frame = scene_control(
            scene_id,
            seq=self._next_fastcon_seq(),
            source_addr=source_addr,
        )
        frame = apply_family_token(frame, self.family.bletoken)
        return await self._async_send_fastcon(frame)

    async def send_status_query(
        self,
        addresses: Iterable[int],
        *,
        delay: int = 0,
    ) -> int:
        """Query device status through every active family gateway."""
        gateways = list(self.online_gateways)
        if not gateways or self._sender is None:
            return 0
        query_addresses = list(addresses)
        sent = 0
        for gateway in gateways:
            assert gateway.peer is not None
            packet = pack_status_query(
                query_addresses,
                sequence=self._next_gateway_seq(),
                delay=delay,
            )
            _LOGGER.debug(
                "Sending Bluetooth status query gateway=%s peer=%s addresses=%s frame=%s",
                gateway.mac,
                gateway.peer,
                query_addresses,
                packet.hex(),
            )
            self._sender(packet, gateway.peer)
            sent += 1
        return sent
