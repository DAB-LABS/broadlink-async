"""Tests for Bluetooth light encoding."""

import pytest

from broadlink_async.magic import (
    CommandError,
    encode_light_brightness,
    encode_light_power,
    encode_rgbcw_light,
)


def test_encode_light_commands() -> None:
    assert encode_light_power(True) == b"\x80"
    assert encode_light_power(False) == b"\x00"
    assert encode_light_brightness(255) == b"\x7f"
    assert encode_light_brightness(128) == b"\x40"
    assert encode_light_brightness(0) == b"\x00"


def test_reject_invalid_brightness() -> None:
    with pytest.raises(CommandError):
        encode_light_brightness(256)


def test_encode_rgbcw_light() -> None:
    assert encode_rgbcw_light(
        on=True,
        brightness=128,
        rgb=(20, 30, 10),
    ) == bytes((64, 10, 20, 30, 0, 0))
    assert encode_rgbcw_light(
        on=True,
        brightness=255,
        cold_percent=50,
    ) == bytes((127, 0, 0, 0, 127, 128))
    assert encode_rgbcw_light(on=False) == bytes(6)
