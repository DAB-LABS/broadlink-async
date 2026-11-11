"""Tests for edgeservice-compatible local LAN framing."""

import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from broadlink_async.magic.lan import (
    AES_PUBLIC_IV,
    LAN_CONTROL,
    LAN_CONTROL_RESPONSE,
    UART_BLE_CONTROL,
    UART_MAGIC,
    pack_lan_control,
    pack_lan_heartbeat,
    pack_lan_packet,
    parse_lan_response,
    unpack_lan_response,
)

AES_KEY = "00112233445566778899aabbccddeeff"


def test_pack_lan_control() -> None:
    fastcon = bytes.fromhex("d0010336223401000000000000000000000000000000")
    packet = pack_lan_control(
        fastcon,
        devtype=0xAF8B,
        mac="aabbccddeeff",
        aes_key=AES_KEY,
        sequence=0x8123,
    )

    assert struct.unpack_from("<H", packet, 38)[0] == LAN_CONTROL
    assert struct.unpack_from("<H", packet, 40)[0] == 0x8123
    assert packet[42:48] == bytes.fromhex("ffeeddccbbaa")
    checksum = struct.unpack_from("<H", packet, 32)[0]
    without_checksum = bytearray(packet)
    without_checksum[32:34] = b"\0\0"
    assert checksum == (0xBEAF + sum(without_checksum)) & 0xFFFF

    decryptor = Cipher(
        algorithms.AES(bytes.fromhex(AES_KEY)),
        modes.CBC(AES_PUBLIC_IV),
    ).decryptor()
    plaintext = decryptor.update(packet[56:]) + decryptor.finalize()
    assert struct.unpack_from("<I", plaintext, 0)[0] == UART_MAGIC
    assert struct.unpack_from("<H", plaintext, 6)[0] == UART_BLE_CONTROL
    assert plaintext[12 : 12 + len(fastcon)] == fastcon


def test_pack_heartbeat_and_parse_response() -> None:
    packet = pack_lan_heartbeat(
        devtype=0xAF8B,
        mac="aabbccddeeff",
        aes_key=AES_KEY,
        sequence=9,
    )
    assert struct.unpack_from("<H", packet, 38)[0] == 105

    response = bytearray(48)
    struct.pack_into("<Q", response, 0, 0x55AAA55A55AAA55A)
    struct.pack_into("<H", response, 38, LAN_CONTROL_RESPONSE)
    struct.pack_into("<H", response, 40, 9)
    assert parse_lan_response(response) == (LAN_CONTROL_RESPONSE, 0, 9)


def test_unpack_encrypted_control_response() -> None:
    fastcon = bytes.fromhex("d0010336223401000000000000000000000000000000")
    response = pack_lan_packet(
        fastcon,
        uart_type=UART_BLE_CONTROL,
        message_type=LAN_CONTROL_RESPONSE,
        devtype=0xAF8B,
        mac="aabbccddeeff",
        aes_key=AES_KEY,
        sequence=7,
    )
    message_type, status, sequence, uart_type, payload = unpack_lan_response(
        response, AES_KEY
    )
    assert (message_type, status, sequence, uart_type) == (
        LAN_CONTROL_RESPONSE,
        0,
        7,
        UART_BLE_CONTROL,
    )
    assert payload == fastcon
