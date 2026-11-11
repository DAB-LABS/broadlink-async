"""Tests for the shared inbound gateway UDP registry."""

from typing import cast

from broadlink_async.magic import (
    MSG_CONTROL,
    MSG_DISCOVERY,
    MSG_DISCOVERY_RESPONSE,
    MSG_HEARTBEAT,
    MSG_HEARTBEAT_RESPONSE,
    MSG_STATUS_ACK,
    MSG_STATUS_UPLOAD,
    InboundGatewayRegistry,
    gateway_mac_from_handshake,
    pack_message,
    parse_status_upload,
    unpack_header,
)


class FakeTransport:
    """Capture UDP responses."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


def test_registry_ignores_short_packets_from_learned_peer() -> None:
    registry = InboundGatewayRegistry(local_mac=bytes.fromhex("010203040506"))
    transport = FakeTransport()
    registry.transport = cast("object", transport)  # type: ignore[assignment]
    received: list[bytes] = []
    registry.register("aabbccddeeff", lambda data, _addr: received.append(data))
    peer = ("192.0.2.10", 41001)
    heartbeat = pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("aabbccddeeff"))
    registry.datagram_received(heartbeat, peer)
    transport.sent.clear()
    received.clear()

    for length in range(4):
        registry.datagram_received(b"\x0f" * length, peer)
        registry.datagram_received(b"\x0f" * length, ("192.0.2.99", 1))
    assert received == []
    assert transport.sent == []

    registry.datagram_received(heartbeat, peer)
    assert received == [heartbeat]
    assert len(transport.sent) == 1


def test_registry_routes_handshake_and_remembers_peer() -> None:
    registry = InboundGatewayRegistry(local_mac=bytes.fromhex("010203040506"))
    transport = FakeTransport()
    registry.transport = cast("object", transport)  # type: ignore[assignment]
    received: list[bytes] = []
    registry.register("aabbccddeeff", lambda data, _addr: received.append(data))
    peer = ("192.0.2.10", 41001)

    heartbeat = pack_message(
        MSG_HEARTBEAT,
        9,
        bytes.fromhex("aabbccddeeff"),
    )
    registry.datagram_received(heartbeat, peer)

    assert received == [heartbeat]
    response, response_peer = transport.sent[0]
    assert unpack_header(response) == (MSG_HEARTBEAT_RESPONSE, 9)
    assert response[4:] == bytes.fromhex("010203040506")
    assert response_peer == peer

    control = pack_message(MSG_CONTROL, 10, b"ignored inbound")
    registry.datagram_received(control, peer)
    assert received[-1] == control

    new_peer = ("192.0.2.10", 42001)
    registry.datagram_received(heartbeat, new_peer)
    received_count = len(received)
    registry.datagram_received(control, peer)
    assert len(received) == received_count


def test_registry_moves_peer_only_on_handshake() -> None:
    registry = InboundGatewayRegistry(local_mac=b"\0" * 6)
    transport = FakeTransport()
    registry.transport = cast("object", transport)  # type: ignore[assignment]
    received: list[tuple[bytes, tuple[str, int]]] = []
    registry.register("aabbccddeeff", lambda data, addr: received.append((data, addr)))
    heartbeat = pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("aabbccddeeff"))
    control = pack_message(MSG_CONTROL, 2, b"payload")
    old_peer = ("192.0.2.10", 41001)
    new_peer = ("198.51.100.20", 41001)
    registry.datagram_received(heartbeat, old_peer)

    registry.datagram_received(control, new_peer)
    assert received == [(heartbeat, old_peer)]

    registry.datagram_received(heartbeat, new_peer)
    registry.datagram_received(control, old_peer)
    registry.datagram_received(control, new_peer)
    assert received[1:] == [(heartbeat, new_peer), (control, new_peer)]


def test_registry_replies_to_discovery_and_ignores_unknown_mac() -> None:
    registry = InboundGatewayRegistry(local_mac=b"\0" * 6)
    transport = FakeTransport()
    registry.transport = cast("object", transport)  # type: ignore[assignment]
    received: list[bytes] = []
    registry.register("aabbccddeeff", lambda data, _addr: received.append(data))

    unknown = pack_message(MSG_DISCOVERY, 1, bytes.fromhex("112233445566"))
    registry.datagram_received(unknown, ("192.0.2.11", 42001))
    assert not received
    assert not transport.sent

    discovery = pack_message(MSG_DISCOVERY, 2, bytes.fromhex("aabbccddeeff"))
    registry.datagram_received(discovery, ("192.0.2.10", 41001))
    assert unpack_header(transport.sent[0][0]) == (MSG_DISCOVERY_RESPONSE, 2)


def test_status_upload_is_parsed_and_acknowledged() -> None:
    command = b"\x40\x01\x02\x03\x04\x05"
    segment = bytes((7 + len(command), 0xC2, 0, 0, 0, 0x34, 0, 0)) + command
    upload = pack_message(MSG_STATUS_UPLOAD, 88, segment)
    assert parse_status_upload(upload) == [(0x234, command)]

    registry = InboundGatewayRegistry(local_mac=b"\0" * 6)
    transport = FakeTransport()
    registry.transport = cast("object", transport)  # type: ignore[assignment]
    registry.register("aabbccddeeff", lambda _data, _addr: None)
    peer = ("192.0.2.10", 41001)
    registry.datagram_received(
        pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("aabbccddeeff")),
        peer,
    )
    transport.sent.clear()
    registry.datagram_received(upload, peer)
    assert unpack_header(transport.sent[0][0]) == (MSG_STATUS_ACK, 88)


def test_invalid_packets_are_rejected() -> None:
    assert gateway_mac_from_handshake(b"\x03") is None
    assert parse_status_upload(pack_message(MSG_STATUS_UPLOAD, 1, b"\x08\xc1")) == []


def test_real_multi_segment_upload_matches_industry() -> None:
    upload = bytes.fromhex(
        "0f009114165122f82e004000010101000000000000000000000000"
        "16c023f83a01004000021b010000000000000000000000"
    )
    assert parse_status_upload(upload) == [
        (1, bytes.fromhex("00021b010000000000000000000000"))
    ]
    valid = bytes((8, 0xC1, 0, 0, 0, 2, 0, 0, 0x80))
    malformed_tail = b"\x08\xc1"
    assert parse_status_upload(
        pack_message(MSG_STATUS_UPLOAD, 1, valid + malformed_tail)
    ) == [(0x102, b"\x80")]
