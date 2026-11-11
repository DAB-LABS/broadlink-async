"""Tests for RM Max discovery and FastCon framing."""

import struct

from broadlink_async.magic import (
    RM_MAX_DEVTYPE,
    apply_family_token,
    build_probe_request,
    device_control,
    parse_probe_response,
    scene_control,
)


def test_build_probe_request() -> None:
    packet = build_probe_request(0x8123)

    assert len(packet) == 48
    assert struct.unpack_from("<Q", packet, 0)[0] == 0x55AAA55A55AAA55A
    assert struct.unpack_from("<H", packet, 38)[0] == 6
    assert struct.unpack_from("<H", packet, 40)[0] == 0x8123
    checksum = struct.unpack_from("<H", packet, 32)[0]
    without_checksum = bytearray(packet)
    without_checksum[32:34] = b"\0\0"
    assert checksum == (0xBEAF + sum(without_checksum)) & 0xFFFF


def test_parse_rmmax_probe_response() -> None:
    packet = bytearray(48 + 16 + 64)
    struct.pack_into("<Q", packet, 0, 0x55AAA55A55AAA55A)
    struct.pack_into("<H", packet, 38, 7)
    struct.pack_into("<H", packet, 48 + 4, RM_MAX_DEVTYPE)
    packet[48 + 10 : 48 + 16] = bytes.fromhex("ffeeddccbbaa")
    packet[64:70] = b"RM Max"
    packet[127] = 1

    result = parse_probe_response(bytes(packet), "192.0.2.10")

    assert result is not None
    assert result.host == "192.0.2.10"
    assert result.mac == "aabbccddeeff"
    assert result.devtype == RM_MAX_DEVTYPE
    assert result.name == "RM Max"
    assert result.locked is True


def test_parse_probe_ignores_other_device_types() -> None:
    packet = bytearray(48 + 16)
    struct.pack_into("<Q", packet, 0, 0x55AAA55A55AAA55A)
    struct.pack_into("<H", packet, 38, 7)
    struct.pack_into("<H", packet, 48 + 4, 0x1234)

    assert parse_probe_response(bytes(packet), "192.0.2.10") is None


def test_fastcon_device_control_and_passthrough() -> None:
    frame = device_control(
        0x1234,
        b"\x01",
        seq=1,
        source_addr=2,
    )

    assert len(frame) == 22
    assert frame[0] == 0xD2
    assert frame[1] == 1
    assert frame[2] == 2
    assert frame[4:7] == b"\x22\x34\x01"
    assert frame[3] == sum(frame[:3] + frame[4:]) & 0xFF

    transformed = apply_family_token(frame, "00010203")
    assert transformed[2] == 3
    assert transformed[3] == sum(transformed[:3] + transformed[4:]) & 0xFF


def test_scene_control_matches_reference_library_vector() -> None:
    assert scene_control(193, seq=0x83, source_addr=3).hex() == (
        "d08303523b0000c10000000000000000000000000000"
    )
