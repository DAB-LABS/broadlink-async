"""BroadLink local LAN heartbeat and AES control framing."""

from __future__ import annotations

import asyncio
import socket
import struct
from collections.abc import Callable
from contextlib import suppress

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import NETWORK_HEADER_LENGTH, NETWORK_MAGIC
from .exceptions import ProtocolError
from .models import normalize_mac

AES_HEADER_LENGTH = 8
AES_PUBLIC_IV = bytes.fromhex("562e17996d093d28ddb3ba695a2e6f58")
LAN_HEARTBEAT = 105
LAN_HEARTBEAT_RESPONSE = 1005
LAN_CONTROL = 106
LAN_CONTROL_RESPONSE = 1006
UART_MAGIC = 0x5A5AA5A5
UART_HEADER_LENGTH = 12
UART_BLE_CONTROL = 0x0907
UART_SUBDEVICE_CONTROL = 0x0B02


def lan_checksum(data: bytes | bytearray) -> int:
    """Return the BroadLink LAN checksum."""
    return (0xBEAF + sum(data)) & 0xFFFF


def build_uart_payload(payload: bytes, uart_type: int) -> bytes:
    """Build the inner DNA UART frame."""
    frame = bytearray(UART_HEADER_LENGTH + len(payload))
    struct.pack_into(
        "<IHHHH",
        frame,
        0,
        UART_MAGIC,
        0,
        uart_type,
        len(payload),
        1,
    )
    frame[UART_HEADER_LENGTH:] = payload
    struct.pack_into("<H", frame, 4, lan_checksum(frame))
    return bytes(frame)


def _decode_aes_key(aes_key: str) -> bytes:
    try:
        key = bytes.fromhex(aes_key)
    except ValueError as err:
        raise ProtocolError("gateway AES key must be hexadecimal") from err
    if len(key) < 16:
        raise ProtocolError("gateway AES key must contain at least 16 bytes")
    return key[:16]


def pack_lan_packet(
    payload: bytes,
    *,
    uart_type: int,
    message_type: int,
    devtype: int,
    mac: str,
    aes_key: str,
    sequence: int,
) -> bytes:
    """Encrypt and wrap one local LAN packet as implemented by edgeservice."""
    key = _decode_aes_key(aes_key)
    plaintext = bytearray(build_uart_payload(payload, uart_type))
    plaintext.extend(bytes(16 - len(plaintext) % 16))

    encryptor = Cipher(algorithms.AES(key), modes.CBC(AES_PUBLIC_IV)).encryptor()
    encrypted = encryptor.update(bytes(plaintext)) + encryptor.finalize()

    packet = bytearray(NETWORK_HEADER_LENGTH + AES_HEADER_LENGTH + len(encrypted))
    struct.pack_into("<Q", packet, 0, NETWORK_MAGIC)
    struct.pack_into("<H", packet, 36, devtype)
    struct.pack_into("<H", packet, 38, message_type)
    struct.pack_into("<H", packet, 40, sequence & 0xFFFF)
    mac_bytes = bytes.fromhex(normalize_mac(mac))
    if len(mac_bytes) != 6:
        raise ProtocolError("gateway MAC must contain six bytes")
    packet[42:48] = reversed(mac_bytes)
    struct.pack_into("<iHH", packet, 48, 1, lan_checksum(plaintext), 0)
    packet[56:] = encrypted
    struct.pack_into("<H", packet, 32, lan_checksum(packet))
    return bytes(packet)


def pack_lan_control(
    fastcon_payload: bytes,
    *,
    devtype: int,
    mac: str,
    aes_key: str,
    sequence: int,
) -> bytes:
    """Pack a FastCon command for local UDP port 80."""
    return pack_lan_packet(
        fastcon_payload,
        uart_type=UART_BLE_CONTROL,
        message_type=LAN_CONTROL,
        devtype=devtype,
        mac=mac,
        aes_key=aes_key,
        sequence=sequence,
    )


def pack_lan_heartbeat(
    *,
    devtype: int,
    mac: str,
    aes_key: str,
    sequence: int,
) -> bytes:
    """Pack a local LAN heartbeat."""
    return pack_lan_packet(
        b"",
        uart_type=UART_SUBDEVICE_CONTROL,
        message_type=LAN_HEARTBEAT,
        devtype=devtype,
        mac=mac,
        aes_key=aes_key,
        sequence=sequence,
    )


def parse_lan_response(data: bytes) -> tuple[int, int, int]:
    """Return message type, status, and sequence from a LAN response."""
    if len(data) < NETWORK_HEADER_LENGTH:
        raise ProtocolError("LAN response is too short")
    if struct.unpack_from("<Q", data, 0)[0] != NETWORK_MAGIC:
        raise ProtocolError("invalid LAN response magic")
    return (
        struct.unpack_from("<H", data, 38)[0],
        struct.unpack_from("<h", data, 34)[0],
        struct.unpack_from("<H", data, 40)[0],
    )


def unpack_lan_response(
    data: bytes,
    aes_key: str,
) -> tuple[int, int, int, int | None, bytes]:
    """Decrypt a LAN response and return its UART type and payload."""
    message_type, status, sequence = parse_lan_response(data)
    if status != 0 or len(data) < NETWORK_HEADER_LENGTH + AES_HEADER_LENGTH + 16:
        return message_type, status, sequence, None, b""

    key = _decode_aes_key(aes_key)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(AES_PUBLIC_IV)).decryptor()
    plaintext = decryptor.update(data[56:]) + decryptor.finalize()
    expected_checksum = struct.unpack_from("<H", data, 52)[0]
    if lan_checksum(plaintext) != expected_checksum:
        raise ProtocolError("invalid LAN AES payload checksum")
    if len(plaintext) < UART_HEADER_LENGTH:
        return message_type, status, sequence, None, b""
    if struct.unpack_from("<I", plaintext, 0)[0] != UART_MAGIC:
        return message_type, status, sequence, None, b""
    uart_checksum = struct.unpack_from("<H", plaintext, 4)[0]
    uart_type = struct.unpack_from("<H", plaintext, 6)[0]
    payload_length = struct.unpack_from("<H", plaintext, 8)[0]
    uart_frame = bytearray(plaintext[: UART_HEADER_LENGTH + payload_length])
    struct.pack_into("<H", uart_frame, 4, 0)
    if lan_checksum(uart_frame) != uart_checksum:
        raise ProtocolError("invalid UART payload checksum")
    return (
        message_type,
        status,
        sequence,
        uart_type,
        bytes(plaintext[UART_HEADER_LENGTH : UART_HEADER_LENGTH + payload_length]),
    )


async def send_lan_packet(
    data: bytes,
    address: tuple[str, int],
    *,
    timeout: float = 3,
) -> bytes:
    """Send a LAN packet twice and wait for the gateway response."""

    def _send() -> bytes:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(data, address)
            sock.sendto(data, address)
            response, _source = sock.recvfrom(1460)
            return response

    return await asyncio.to_thread(_send)


class _PersistentLanProtocol(asyncio.DatagramProtocol):
    """Receive all datagrams from one connected gateway socket."""

    def __init__(self, callback: Callable[[bytes], None]) -> None:
        self.callback = callback

    def datagram_received(self, data: bytes, _addr: tuple[str, int]) -> None:
        self.callback(data)


class LanGatewayConnection:
    """Persistent edgeservice-style LAN connection to one gateway."""

    def __init__(
        self,
        transport: asyncio.DatagramTransport,
        *,
        host: str,
        devtype: int,
        mac: str,
        aes_key: str,
    ) -> None:
        self.transport = transport
        self.host = host
        self.devtype = devtype
        self.mac = mac
        self.aes_key = aes_key
        self._sequence = 0x8000
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    @classmethod
    async def create(
        cls,
        *,
        host: str,
        devtype: int,
        mac: str,
        aes_key: str,
        callback: Callable[[bytes], None],
    ) -> LanGatewayConnection:
        """Open a connected UDP socket and start heartbeats."""
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _PersistentLanProtocol(callback),
            remote_addr=(host, 80),
        )
        return cls(
            transport,
            host=host,
            devtype=devtype,
            mac=mac,
            aes_key=aes_key,
        )

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFFFF
        if self._sequence == 0:
            self._sequence = 1
        return self._sequence

    def send_heartbeat(self) -> None:
        """Send one LAN heartbeat over the persistent socket."""
        self.transport.sendto(
            pack_lan_heartbeat(
                devtype=self.devtype,
                mac=self.mac,
                aes_key=self.aes_key,
                sequence=self._next_sequence(),
            )
        )

    def send_control(self, fastcon_payload: bytes) -> None:
        """Send one FastCon command twice over the persistent socket."""
        packet = pack_lan_control(
            fastcon_payload,
            devtype=self.devtype,
            mac=self.mac,
            aes_key=self.aes_key,
            sequence=self._next_sequence(),
        )
        self.transport.sendto(packet)
        self.transport.sendto(packet)

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                self.send_heartbeat()
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise

    async def async_close(self) -> None:
        """Stop heartbeats and close the UDP socket."""
        self._heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._heartbeat_task
        self.transport.close()
        await asyncio.sleep(0)
