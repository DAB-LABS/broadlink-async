"""Tests for remote encoding and gateway fan-out."""

import pytest

from broadlink_async.magic import (
    MSG_CONTROL,
    MSG_HEARTBEAT,
    MSG_STATUS_UPLOAD,
    CommandError,
    DiscoveredRMMax,
    Family,
    GatewaySet,
    ImportedDevice,
    ProtocolError,
    RMProfile,
    encode_channel,
    encode_commands,
    encode_profile_commands,
    encode_step,
    pack_message,
    supports_profile_command,
)


def test_remote_payloads_match_industry_vectors() -> None:
    assert encode_commands(["power"]) == [b"\x01"]
    assert encode_channel(120) == [b"\x06", b"\x07", b"\x0f"]
    assert encode_step("volume", -3) == [b"\x12", b"\x12", b"\x12"]


@pytest.mark.parametrize(
    ("profile", "commands", "expected"),
    [
        (RMProfile.PROJECTOR, ["power", "blue"], [b"\x01", b"\x2e"]),
        (RMProfile.CURTAIN, ["open", "reverse"], [b"\x01", b"\x05"]),
        (RMProfile.RELAY_PANEL, ["channel_2_on", "all_off"], [b"\x21", b"\xf0"]),
        (RMProfile.FAN, ["oscillate", "timer"], [b"\x02", b"\x37"]),
        (RMProfile.RM_LIGHT, ["soft", "red"], [b"\x08", b"\x2b"]),
        (RMProfile.DRYING_RACK, ["heat_dry", "light_off"], [b"\x05", b"\x08"]),
        (RMProfile.PURIFIER, ["auto", "sleep"], [b"\x3d", b"\x39"]),
        (RMProfile.WATER_HEATER, ["temperature_up"], [b"\x03"]),
        (RMProfile.HUMIDIFIER, ["level", "speed"], [b"\x08", b"\x38"]),
        (RMProfile.VACUUM, ["charge", "auto"], [b"\x3b", b"\x3d"]),
    ],
)
def test_profile_command_vectors(
    profile: RMProfile,
    commands: list[str],
    expected: list[bytes],
) -> None:
    assert encode_profile_commands(profile, commands) == expected


def test_profile_command_errors_are_explicit() -> None:
    with pytest.raises(CommandError, match="unsupported fan command"):
        encode_profile_commands(RMProfile.FAN, ["not_a_command"])
    with pytest.raises(ProtocolError, match="no imported learned keys"):
        encode_profile_commands(RMProfile.LEARNED_IR, ["power"])
    with pytest.raises(ProtocolError, match="not supported"):
        encode_profile_commands(RMProfile.AC, ["power"])


@pytest.mark.parametrize(
    ("profile", "functions", "commands", "expected"),
    [
        (
            RMProfile.RM_LIGHT,
            {"on": 1, "white": 64},
            ["turn_on", "white"],
            [b"\x01", b"\x40"],
        ),
        (
            RMProfile.TV,
            {"power": 9, "volume_up": 0x51},
            ["power", "volume_up"],
            [b"\x09", b"\x51"],
        ),
        (RMProfile.DRYING_RACK, {"dry_up": 7}, ["up"], [b"\x07"]),
        (
            RMProfile.CURTAIN,
            {"motor_open": 1, "motor_pause": 3},
            ["open", "stop"],
            [b"\x01", b"\x03"],
        ),
        (
            RMProfile.RELAY_PANEL,
            {"switch2_open": 0x21, "switch_all_close": 0xF0},
            ["channel_2_on", "all_off"],
            [b"\x21", b"\xf0"],
        ),
        (RMProfile.LEARNED_IR, {"红外开关": 1}, ["红外开关"], [b"\x01"]),
        (RMProfile.LEARNED_RF, {"射频开关": 2}, ["射频开关"], [b"\x02"]),
    ],
)
def test_imported_function_codes_are_authoritative(
    profile: RMProfile,
    functions: dict[str, int],
    commands: list[str],
    expected: list[bytes],
) -> None:
    assert encode_profile_commands(profile, commands, functions) == expected


def test_imported_functions_reject_missing_keys() -> None:
    functions = {"dry_up": 1}
    with pytest.raises(CommandError, match="unsupported drying_rack command"):
        encode_profile_commands(RMProfile.DRYING_RACK, ["down"], functions)
    assert supports_profile_command(RMProfile.DRYING_RACK, "up", functions)
    assert not supports_profile_command(RMProfile.DRYING_RACK, "stop", functions)
    assert supports_profile_command(RMProfile.DRYING_RACK, "stop")
    assert not supports_profile_command(RMProfile.LEARNED_IR, "power")


async def test_remote_payload_fans_out_to_all_gateways() -> None:
    sent: list[tuple[bytes, tuple[str, int]]] = []

    def sender(data: bytes, address: tuple[str, int]) -> None:
        sent.append((data, address))

    family = Family(
        family_id="family-1",
        name="Test home",
        bletoken="00010203",
        token="00112233445566778899aabbccddeeff",
        devices=[
            ImportedDevice(
                did="00000000000000000000aabbccddeeff",
                pid="0000000000000000000000008baf0000",
                name="RM Max 1",
                mac="aabbccddeeff",
            ),
            ImportedDevice(
                did="00000000000000000000112233445566",
                pid="0000000000000000000000008baf0000",
                name="RM Max 2",
                mac="112233445566",
            ),
        ],
    )
    gateways = GatewaySet(
        family,
        [
            DiscoveredRMMax("192.0.2.10", "aabbccddeeff", 0xAF8B),
            DiscoveredRMMax("192.0.2.11", "112233445566", 0xAF8B),
        ],
        sender=sender,
    )
    gateways.handle_packet(
        "aabbccddeeff",
        pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("aabbccddeeff")),
        ("192.0.2.10", 41001),
    )
    gateways.handle_packet(
        "112233445566",
        pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("112233445566")),
        ("192.0.2.11", 41002),
    )

    count = await gateways.send_remote_payloads(4660, encode_channel(12))

    assert count == 4
    assert [address for _, address in sent] == [
        ("192.0.2.10", 41001),
        ("192.0.2.11", 41002),
        ("192.0.2.10", 41001),
        ("192.0.2.11", 41002),
    ]
    assert int.from_bytes(sent[0][0][:2], "little") == MSG_CONTROL
    assert sent[0][1] == ("192.0.2.10", 41001)

    sent.clear()
    assert await gateways.send_scene(193) == 2
    assert int.from_bytes(sent[0][0][:2], "little") == MSG_CONTROL


async def test_offline_gateway_is_not_used() -> None:
    sent: list[tuple[bytes, tuple[str, int]]] = []

    def sender(data: bytes, address: tuple[str, int]) -> None:
        sent.append((data, address))

    family = Family(
        family_id="family-1",
        name="Test home",
        bletoken="00010203",
        token="00112233445566778899aabbccddeeff",
        devices=[
            ImportedDevice(
                did="00000000000000000000aabbccddeeff",
                pid="0000000000000000000000008baf0000",
                name="RM Max",
                mac="aabbccddeeff",
            )
        ],
    )
    gateways = GatewaySet(
        family,
        [DiscoveredRMMax("192.0.2.10", "aabbccddeeff", 0xAF8B)],
        sender=sender,
    )
    assert await gateways.send_remote_payloads(4660, [b"\x01"]) == 0
    assert sent == []


async def test_session_expires_after_industry_timeout() -> None:
    family = Family(
        family_id="family-1",
        name="Test home",
        bletoken="00010203",
        devices=[
            ImportedDevice(
                did="00000000000000000000aabbccddeeff",
                pid="0000000000000000000000008baf0000",
                name="RM Max",
                mac="aabbccddeeff",
            )
        ],
    )
    sent: list[tuple[bytes, tuple[str, int]]] = []
    gateways = GatewaySet(family, sender=lambda data, addr: sent.append((data, addr)))
    gateways.handle_packet(
        "aabbccddeeff",
        pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("aabbccddeeff")),
        ("192.0.2.10", 41001),
    )
    gateway = gateways.gateways[0]
    gateways.expire_sessions(gateway.last_seen + 180)
    assert await gateways.send_remote_payloads(4660, [b"\x01"]) == 0
    assert sent == []


def test_status_upload_reports_short_address_and_payload() -> None:
    reports: list[tuple[int, bytes]] = []

    family = Family(
        family_id="family-1",
        name="Test home",
        bletoken="00010203",
        token="00112233445566778899aabbccddeeff",
        devices=[
            ImportedDevice(
                did="00000000000000000000aabbccddeeff",
                pid="0000000000000000000000008baf0000",
                name="RM Max",
                mac="aabbccddeeff",
            )
        ],
    )
    gateways = GatewaySet(
        family,
        report_callback=lambda short_addr, payload: reports.append((short_addr, payload)),
    )
    command = b"\x80"
    segment = bytes((7 + len(command), 0xC1, 0, 0, 0, 0x23, 0, 0)) + command
    gateways.handle_packet(
        "aabbccddeeff",
        pack_message(MSG_STATUS_UPLOAD, 7, segment),
        ("192.0.2.10", 41001),
    )
    assert reports == [(0x123, command)]
