"""Tests for RM Max air-conditioner encoding."""

from collections.abc import Callable

import pytest

from broadlink_async.magic import (
    CommandError,
    encode_ac_attribute,
    encode_floor_heating_attribute,
    encode_fresh_air_attribute,
)


def test_encode_three_in_one_attributes() -> None:
    assert encode_floor_heating_attribute("power", 1) == b"\x00\x01\x03"
    assert encode_floor_heating_attribute("power", 0) == b"\x00\x01\x02"
    assert encode_floor_heating_attribute("temperature", 28) == b"\x04\x01\x1c"
    assert encode_fresh_air_attribute("power", 1) == b"\x00\x01\x05"
    assert encode_fresh_air_attribute("power", 0) == b"\x00\x01\x04"
    assert encode_fresh_air_attribute("mode", 3) == b"\x01\x01\x30"
    assert encode_fresh_air_attribute("fan", 5) == b"\x03\x01\x50"


@pytest.mark.parametrize(
    ("encoder", "attribute", "value"),
    [
        (encode_floor_heating_attribute, "power", 2),
        (encode_floor_heating_attribute, "temperature", 15),
        (encode_floor_heating_attribute, "temperature", 46),
        (encode_floor_heating_attribute, "mode", 1),
        (encode_fresh_air_attribute, "power", 2),
        (encode_fresh_air_attribute, "mode", 0),
        (encode_fresh_air_attribute, "mode", 7),
        (encode_fresh_air_attribute, "fan", 0),
        (encode_fresh_air_attribute, "fan", 6),
        (encode_fresh_air_attribute, "temperature", 20),
    ],
)
def test_reject_invalid_three_in_one_attributes(
    encoder: Callable[[str, int], bytes], attribute: str, value: int
) -> None:
    with pytest.raises(CommandError):
        encoder(attribute, value)


def test_encode_ac_attributes() -> None:
    assert encode_ac_attribute("power", 1) == b"\x00\x01\x01"
    assert encode_ac_attribute("mode", 2) == b"\x01\x01\x02"
    assert encode_ac_attribute("temperature", 26) == b"\x02\x01\x1a"
    assert encode_ac_attribute("fan", 3) == b"\x03\x01\x03"


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("unknown", 1),
        ("power", 2),
        ("mode", 3),
        ("temperature", 31),
        ("fan", 4),
    ],
)
def test_reject_invalid_ac_attributes(attribute: str, value: int) -> None:
    with pytest.raises(CommandError):
        encode_ac_attribute(attribute, value)
