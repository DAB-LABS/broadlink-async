"""Decode LIFAair LM05 frames captured from a real device.

Bytes are payload offsets 27..57 from firmware 10026, polled on 2026-11-17.
"""

from __future__ import annotations

import asyncio

import pytest

from broadlink_async.purifier import lifaair
from tests.oracle.harness import HOST, MAC


def payload(raw_hex: str) -> bytes:
    """Return a GET_STATE body with captured bytes placed at offset 27."""
    data = bytearray(58)
    data[27:] = bytes.fromhex(raw_hex)
    return bytes(data)


def device() -> lifaair:
    """Return a lifaair instance that does not touch the network."""
    return lifaair(HOST, MAC, 0x4EC2)


def run(coro):
    return asyncio.run(coro)


# Station up, purifier not yet online. 14:31:15.
OFFLINE_BOOT = (
    "00 00 00 02 90 01 00 00 09 00 02 00 02 00 03 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 01 00 c0"
)
# Unpaired after the pairing window. 15:11:10.
OFFLINE_UNPAIRED = (
    "00 00 00 02 ab 03 00 00 09 00 01 00 00 00 01 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 01 00 c0"
)
# First online frame after each reconnection: fan_state 0xA5, climate 00 00 00.
RECONNECT_ZEROS = (
    (
        "00 00 00 02 b5 03 00 00 0a 00 01 00 00 00 02 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 a5 2b c0",
        43,
    ),
    (
        "00 00 00 02 ee 03 00 00 0a 00 00 00 00 00 01 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 a5 2b c0",
        43,
    ),
    (
        "00 00 00 02 90 01 00 00 0a 00 00 00 01 00 02 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 a5 14 c0",
        20,
    ),
    (
        "00 00 00 02 a8 03 00 00 0a 00 00 00 00 00 01 00 "
        "00 00 00 00 00 00 00 00 00 00 00 00 a5 2b c0",
        43,
    ),
)
# Next frame after the 14:44:57 placeholder. 14:45:01.
AFTER_RECONNECT = (
    "08 01 16 02 be 03 00 00 09 00 01 00 00 00 01 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 a5 2b c0"
)
# Spray peak. 14:33:05.
SPRAY = (
    "0a 01 16 02 9f 03 00 00 09 00 0c 00 27 00 80 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 a5 0d c0"
)


def decode(raw_hex: str) -> dict:
    """Decode one captured frame."""
    return device()._decode_state(payload(raw_hex))


def response(fan: int, speed: int, flags: int) -> bytes:
    """Return a state payload with a real climate reading and one fan triple."""
    data = bytearray(58)
    data[27:30] = b"\x0b\x01\x16"  # 26.7 C, 22 %
    data[55] = fan
    data[56] = speed
    data[57] = flags
    return bytes(data)


def test_offline_purifier_climate_and_mode_are_none():
    """Unplugged and unpaired both report 0x01 with zero climate bytes."""
    for raw_hex in (OFFLINE_BOOT, OFFLINE_UNPAIRED):
        state = decode(raw_hex)
        assert state["temperature"] is None
        assert state["humidity"] is None
        assert state["fan_mode"] is None
        assert state["fan_speed"] is None
        assert state["purifier_online"] is False


def test_reconnect_placeholder_then_real_climate():
    """00 00 00 climate is not 0.0 deg C / 0 %; the next frame is the reading."""
    for raw_hex, speed in RECONNECT_ZEROS:
        state = decode(raw_hex)
        assert state["temperature"] is None
        assert state["humidity"] is None
        assert state["fan_mode"] == lifaair.FanMode.AUTO
        assert state["fan_speed"] == speed
    state = decode(AFTER_RECONNECT)
    assert state["temperature"] == 26.4
    assert state["humidity"] == 22


def test_spray_frame_keeps_pm_order_and_zero_formaldehyde():
    """PM offsets stay as verified, and a zero HCHO reading stays 0.0."""
    state = decode(SPRAY)
    assert state["formaldehyde"] == 0.0
    assert state["pm1"] == 12
    assert state["pm2_5"] == 39
    assert state["pm10"] == 128


def test_fan_mode_and_speed_are_reported_independently():
    """Reported mode and speed are not rewritten."""
    cases = (
        # AUTO speed 0, clean air. 14:46:10.
        (
            "09 01 16 02 dc 03 00 00 0a 00 01 00 00 00 01 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 a5 00 c0",
            lifaair.FanMode.AUTO,
            0,
        ),
        # OFF reported speed 50 after set_fan_speed(50). 14:50:25.
        (
            "0b 01 16 02 8f 03 00 00 0a 00 00 00 00 00 01 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 81 32 c0",
            lifaair.FanMode.OFF,
            50,
        ),
        # NIGHT. 14:50:48.
        (
            "0b 01 16 02 8d 03 00 00 0a 00 01 00 00 00 01 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 95 0a c0",
            lifaair.FanMode.NIGHT,
            10,
        ),
        # TURBO. 14:50:58.
        (
            "0b 01 16 02 8b 03 00 00 09 00 01 00 00 00 01 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 8d 79 c0",
            lifaair.FanMode.TURBO,
            121,
        ),
        # ANTI_ALLERGY is 0x85 with flags 0x80. 14:50:04.
        (
            "0b 01 16 02 90 03 00 00 09 00 00 00 00 00 02 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 85 3c 80",
            lifaair.FanMode.ANTI_ALLERGY,
            60,
        ),
        # MANUAL reported at speed 0. 14:51:18.
        (
            "0b 01 16 02 88 03 00 00 09 00 01 00 00 00 02 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 85 00 c0",
            lifaair.FanMode.MANUAL,
            0,
        ),
        # MANUAL speed 50. 14:51:28.
        (
            "0b 01 16 02 89 03 00 00 0a 00 02 00 00 00 02 00 "
            "00 00 00 00 00 00 00 00 00 00 00 00 85 32 c0",
            lifaair.FanMode.MANUAL,
            50,
        ),
    )
    for raw_hex, mode, speed in cases:
        state = decode(raw_hex)
        assert state["fan_mode"] == mode
        assert state["fan_speed"] == speed


def test_set_fan_mode_without_a_command_raises():
    """MANUAL, UNKNOWN and None have no mode argument."""
    dev = device()
    for mode in (lifaair.FanMode.MANUAL, lifaair.FanMode.UNKNOWN, None):
        with pytest.raises(ValueError):
            run(dev.set_fan_mode(mode))


def test_set_fan_speed_rejects_out_of_range():
    """Speeds outside 0..121 are rejected."""
    dev = device()
    for speed in (-1, 122):
        with pytest.raises(ValueError):
            run(dev.set_fan_speed(speed))


def test_bit0_clear_decodes_as_the_same_mode():
    """0x84, 0xA4 and 0x80 are MANUAL, AUTO and OFF."""
    cases = (
        (0x84, 0x32, 0xC0, lifaair.FanMode.MANUAL, 50),
        (0xA4, 0x1E, 0xC0, lifaair.FanMode.AUTO, 30),
        (0x80, 0x00, 0xC0, lifaair.FanMode.OFF, 0),
    )
    for fan, speed, flags, mode, expect_speed in cases:
        state = device()._decode_state(response(fan, speed, flags))
        assert state["fan_mode"] == mode
        assert state["fan_speed"] == expect_speed
