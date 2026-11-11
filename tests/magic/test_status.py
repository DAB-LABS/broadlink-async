"""Tests for FastCon status parsing."""

import pytest

from broadlink_async.magic import (
    ImportedDevice,
    device_control,
    parse_device_upload,
    parse_fastcon_report,
)


def test_parse_light_report() -> None:
    payload = bytes((64, 10, 20, 30, 127, 128))
    frame = device_control(257, payload, seq=1, source_addr=3)
    report = parse_fastcon_report(frame)
    assert report is not None
    assert report.short_addr == 257
    light = ImportedDevice(
        did="gateway",
        pid="",
        name="Light",
        sdid="light",
        spid="0000000000000000000000002aa80000",
        ble_category="RGBCWLIGHT",
    )
    assert parse_device_upload(light, report.command) == {
        "is_on": True,
        "brightness": 128,
        "rgb_color": (20, 30, 10),
        "color_temp_kelvin": 4600,
    }


def test_parse_ac_report() -> None:
    ac = ImportedDevice(
        did="gateway",
        pid="",
        name="AC",
        sdid="ac",
        spid="0000000000000000000000008fab0000",
        ble_category="BLEAC",
    )
    assert parse_device_upload(ac, b"\x00\x02\x1b\x01") == {
        "power": 0,
        "mode": 2,
        "temperature": 27,
        "fan": 1,
    }


def test_parse_three_in_one_report() -> None:
    panel = ImportedDevice(
        did="gateway",
        pid="",
        name="Panel",
        sdid="panel",
        spid="000000000000000000000000bbaf0000",
        ble_category="BLEAC",
    )
    assert panel.is_three_in_one
    status = bytes.fromhex("75121a210014171100000000002800")
    assert parse_device_upload(panel, status) == {
        "power": 1,
        "mode": 2,
        "temperature": 26,
        "fan": 1,
        "current_temperature": 20,
        "floor_heating_power": 0,
        "floor_heating_temperature": 23,
        "fresh_air_power": 1,
        "fresh_air_mode": 1,
        "fresh_air_fan": 2,
    }
    below_zero = bytes.fromhex("7011140000ec") + bytes(9)
    assert parse_device_upload(panel, below_zero)["current_temperature"] == -20


@pytest.mark.parametrize(
    "payload",
    [
        "1e1023316307000000000000000000",
        "1e1023316307dd00",
        "7011",
        "70110000001417110000000000280000",
        "701100000014171100000000002800",
        "70331a000014171100000000002800",
    ],
)
def test_ignore_three_in_one_non_status(payload: str) -> None:
    panel = ImportedDevice(
        did="gateway",
        pid="",
        name="Panel",
        sdid="panel",
        spid="000000000000000000000000bbaf0000",
        ble_category="BLEAC",
    )
    assert parse_device_upload(panel, bytes.fromhex(payload)) == {}


def test_rm_child_with_three_in_one_pid_uses_ac_report() -> None:
    ac = ImportedDevice(
        did="gateway",
        pid="",
        name="AC",
        sdid="ac",
        spid="000000000000000000000000bbaf0000",
        ble_category="BLEAC",
        is_rm_child=True,
    )
    assert not ac.is_three_in_one


def test_parse_switch_report() -> None:
    switch = ImportedDevice(
        did="gateway",
        pid="",
        name="Panel",
        sdid="switch",
        ble_category="SWITCH",
    )
    assert parse_device_upload(switch, b"\x05\x04") == {"channels": {0: False, 2: True}}
    assert parse_device_upload(switch, b"\x01") == {}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("0032ff00000000000000000000000000", {"position": 50, "motion": "stopped"}),
        ("0000ff00000000000000000000000000", {"position": 0, "motion": "stopped"}),
        ("010180545000000000000000000000", {"position": 1, "motion": "opening"}),
        ("021e80545000000000000000000000", {"position": 30, "motion": "closing"}),
        ("036480545000000000000000000000", {"position": 100, "motion": "stopped"}),
        ("01ff80545000000000000000000000", {}),
        ("03ff80545000000000000000000000", {}),
        ("03", {}),
    ],
)
def test_parse_curtain_report(payload: str, expected: dict[str, object]) -> None:
    curtain = ImportedDevice(
        did="gateway",
        pid="",
        name="Curtain",
        sdid="curtain",
        spid="0000000000000000000000004fac0000",
        ble_category="CURTAIN",
    )
    assert parse_device_upload(curtain, bytes.fromhex(payload)) == expected
