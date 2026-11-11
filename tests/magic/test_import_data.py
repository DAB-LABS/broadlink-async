"""Tests for Magic Home family import parsing."""

import base64
import json
from pathlib import Path

import pytest

from broadlink_async.magic import (
    DeviceKind,
    ImportDataError,
    ImportedDevice,
    RMProfile,
    parse_import_payload,
)


def _b64(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def _payload_for_devices(
    devices: list[dict[str, object]], family_info: object = None
) -> bytes:
    if family_info is None:
        family_info = {"bletoken": "00010203"}
    return json.dumps(
        [
            {
                "did": "family-1",
                "dataList": [
                    {"mtag": "familyInfo", "data": _b64(family_info)},
                    {"mtag": "devlist", "data": _b64(devices)},
                ],
            }
        ]
    ).encode()


def test_parse_family_with_rmmax_tv_and_stb() -> None:
    family_info = {
        "name": "Test home",
        "bletoken": "00010203",
        "roomlist": [{"roomId": 1, "roomName": "Living room"}],
    }
    devlist = [
        {
            "did": "00000000000000000000aabbccddeeff",
            "pid": "0000000000000000000000008baf0000",
            "mac": "aabbccddeeff",
            "devname": "RM Max",
        },
        {
            "did": "00000000000000000000aabbccddeeff",
            "sdid": "aabbccddeeff_1",
            "spid": "0000000000000000000000002baf0000",
            "shortaddr": "4660",
            "devname": "Television",
        },
        {
            "did": "00000000000000000000aabbccddeeff",
            "sdid": "aabbccddeeff_2",
            "spid": "0000000000000000000000002caf0000",
            "shortaddr": "4661",
            "blecatetory": "STB",
            "devname": "Set-top box",
        },
    ]
    grouplist = [
        {
            "groupId": 65,
            "groupName": "Living room lights",
            "blecatetory": "LIGHT",
            "roomId": 1,
            "roomName": "Living room",
            "containDidList": ["aabbccddeeff_3"],
        }
    ]
    scenelist = [
        {
            "moduleid": "193",
            "name": "Movie",
            "roomId": 1,
            "room": "Living room",
            "moduledev": [],
        }
    ]
    body = json.dumps(
        [
            {
                "did": "family-1",
                "pid": "0000000000000000000000008baf0000",
                "token": "00112233445566778899aabbccddeeff",
                "dataList": [
                    {"mtag": "familyInfo", "data": _b64(family_info)},
                    {"mtag": "devlist", "data": _b64(devlist)},
                    {"mtag": "grouplist", "data": _b64(grouplist)},
                    {"mtag": "scenelist", "data": _b64(scenelist)},
                ],
                "vtsubtoken": [],
            }
        ]
    ).encode()

    families = parse_import_payload(body)

    assert len(families) == 1
    family = families[0]
    assert family.family_id == "family-1"
    assert family.name == "Test home"
    assert family.bletoken == "00010203"
    assert family.token == "00112233445566778899aabbccddeeff"
    assert len(family.gateways) == 1
    assert [device.kind for device in family.remote_devices] == [
        DeviceKind.TV,
        DeviceKind.STB,
    ]
    assert family.remote_devices[0].short_addr == 4660
    assert family.rooms[0].name == "Living room"
    assert family.groups[0].name == "Living room lights"
    assert family.scenes[0].scene_id == "193"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{}",
        b"not json",
        json.dumps([{"did": "", "dataList": []}]).encode(),
        json.dumps(
            [{"did": "family", "dataList": [{"mtag": "devlist", "data": "!"}]}]
        ).encode(),
    ],
)
def test_invalid_import_payload(body: bytes) -> None:
    with pytest.raises(ImportDataError):
        parse_import_payload(body)


@pytest.mark.parametrize("short_addr", [[], {"x": 1}, True, 1.5, "secret-value", "0xZZ"])
def test_invalid_import_field_types_do_not_echo_values(short_addr: object) -> None:
    body = _payload_for_devices(
        [{"did": "gateway", "pid": "", "name": "Lamp", "shortaddr": short_addr}]
    )
    with pytest.raises(ImportDataError) as err:
        parse_import_payload(body)
    assert "secret" not in str(err.value)
    assert "ZZ" not in str(err.value)


@pytest.mark.parametrize("bletoken", ["", "  ", "secret-value", "0x0102", "abc"])
def test_missing_or_invalid_bletoken_is_rejected(bletoken: str) -> None:
    body = _payload_for_devices([], {"bletoken": bletoken})
    with pytest.raises(ImportDataError) as err:
        parse_import_payload(body)
    assert "secret" not in str(err.value)


def test_missing_bletoken_without_family_info_is_rejected() -> None:
    body = json.dumps(
        [{"did": "family", "dataList": [{"mtag": "devlist", "data": _b64([])}]}]
    ).encode()
    with pytest.raises(ImportDataError):
        parse_import_payload(body)


def test_gateway_mac_falls_back_to_did() -> None:
    body = _payload_for_devices(
        [
            {
                "did": "00000000000000000000A1B2C3D4E5F6",
                "pid": "0000000000000000000000008baf0000",
                "devname": "RM Max",
            }
        ]
    )
    (gateway,) = parse_import_payload(body)[0].gateways
    assert gateway.mac == "a1b2c3d4e5f6"


@pytest.mark.parametrize("devlist", [[1], ["device"], [{"did": []}], {"devlist": None}])
def test_unexpected_import_structure_is_skipped_or_rejected(devlist: object) -> None:
    body = json.dumps(
        [
            {
                "did": "family",
                "dataList": [
                    {"mtag": "familyInfo", "data": _b64({"bletoken": "00010203"})},
                    {"mtag": "devlist", "data": _b64(devlist)},
                ],
            }
        ]
    ).encode()
    try:
        families = parse_import_payload(body)
    except ImportDataError:
        return
    assert all(not family.devices for family in families)


@pytest.mark.parametrize(
    ("category", "devtype", "kind"),
    [
        ("SWITCH", None, DeviceKind.SWITCH),
        ("PLUG", None, DeviceKind.PLUG),
        ("CURTAIN", None, DeviceKind.CURTAIN),
        ("", 44181, DeviceKind.SWITCH),
    ],
)
def test_switch_and_curtain_device_kinds(
    category: str,
    devtype: int | None,
    kind: DeviceKind,
) -> None:
    device = ImportedDevice(
        did="device",
        pid="",
        name="Device",
        ble_category=category,
        devtype=devtype,
    )
    assert device.kind is kind


def test_actual_rm_child_fixture_profiles_and_family_lists() -> None:
    fixture = Path(__file__).with_name("fixtures") / "rm_child_devlist.json"
    devlist = json.loads(fixture.read_text())
    assert len(devlist) == 23

    family = parse_import_payload(_payload_for_devices(devlist))[0]
    gateway, *children = family.devices

    assert gateway.kind is DeviceKind.GATEWAY
    assert not gateway.is_rm_child
    assert len(children) == 22
    assert all(device.is_rm_child for device in children)
    assert children[-1].rm_profile is None
    assert children[-1].kind is DeviceKind.OTHER
    assert children[-2].rm_profile is RMProfile.LEARNED_RF
    assert children[-2].kind is DeviceKind.OTHER
    assert children[-3].rm_profile is RMProfile.LEARNED_IR
    assert children[-3].kind is DeviceKind.OTHER
    assert len(family.rm_remote_devices) == 7
    assert len(family.rm_companion_devices) == 11
    assert len(family.rm_curtain_devices) == 2
    assert len(family.rm_fan_devices) == 1
    assert len(family.rm_light_devices) == 2
    assert len(family.rm_power_devices) == 3
    assert len(family.rm_vacuum_devices) == 1
    assert len(family.rm_drying_rack_devices) == 1
    assert len(family.rm_relay_devices) == 1
    assert json.dumps(children[0].rm_profile) == '"tv"'


def test_rm_child_requires_gateway_relationship() -> None:
    gateway_did = "00000000000000000000a1b2c3d4e5f6"
    devices = [
        {
            "did": gateway_did,
            "pid": "0000000000000000000000008baf0000",
            "mac": "a1b2c3d4e5f6",
            "sdid": "",
            "devname": "RM Max",
        },
        {
            "did": "ordinary-ble-light",
            "pid": "0000000000000000000000002aa80000",
            "blecatetory": "LIGHT",
            "devname": "BLE light",
        },
        {
            "did": gateway_did,
            "pid": "0000000000000000000000002aa80000",
            "sdid": "a1b2c3d4e5f60001",
            "spid": "0000000000000000000000002aa80000",
            "bledevtype": "GROUP",
            "devname": "Light group",
        },
        {
            "did": gateway_did,
            "pid": "0000000000000000000000008baf0000",
            "sdid": "a1:b2:c3:d4:e5:f6_0002",
            "spid": "0000000000000000000000002aa80000",
            "devname": "RM light",
        },
    ]

    _, ordinary, group, rm_light = parse_import_payload(_payload_for_devices(devices))[
        0
    ].devices

    assert not ordinary.is_rm_child
    assert ordinary.rm_profile is None
    assert ordinary.kind is DeviceKind.LIGHT
    assert not group.is_rm_child
    assert group.kind is DeviceKind.GROUP
    assert rm_light.is_rm_child
    assert rm_light.rm_profile is RMProfile.RM_LIGHT
    assert rm_light.kind is DeviceKind.RM_LIGHT


def test_switch_channels_are_parsed_from_vgroups() -> None:
    gateway_did = "0000000000000000000002ab3ca70761"
    groups = [
        {"name": "按键1", "channel": "0", "blecategory": "SWITCH", "ignoreflag": False},
        {"name": "按键2", "channel": "1", "blecategory": "SWITCH", "ignoreflag": False},
        {"name": "按键3", "channel": "2", "blecategory": "SWITCH", "ignoreflag": False},
        {"groupId": 20, "blecategory": "SWITCH", "ignoreflag": True},
    ]
    devices = [
        {
            "did": gateway_did,
            "pid": "0000000000000000000000008baf0000",
            "mac": "02ab3ca70761",
            "devname": "RM MAX",
        },
        {
            "did": gateway_did,
            "sdid": "0000000000000000000002ab3c2f9432",
            "mac": "02ab3c2f9432",
            "shortaddr": "9",
            "blecatetory": "SWITCH",
            "devname": "三键开关面板",
            "cnt": 0,
            "vGroups": groups,
        },
    ]

    _, panel = parse_import_payload(_payload_for_devices(devices))[0].devices

    assert panel.kind is DeviceKind.SWITCH
    assert panel.channel_count == 3
    assert panel.channel_names == ["按键1", "按键2", "按键3"]


def test_function_list_codes_are_parsed_from_extend() -> None:
    gateway_did = "0000000000000000000002ab3ca70761"
    light_functions = [{"type": 1, "function": "on"}, {"function": "white", "type": 64}]
    learned_functions = [{"type": 1, "name": "红外开关", "function": "extend"}]
    devices = [
        {
            "did": gateway_did,
            "pid": "0000000000000000000000008baf0000",
            "mac": "02ab3ca70761",
            "devname": "RM MAX",
        },
        {
            "did": gateway_did,
            "sdid": "02ab3ca7076100000000000000000004",
            "spid": "00000000000000000000000060b00000",
            "devname": "照明方案",
            "extend": json.dumps({"functionList": light_functions}),
            "extendInfo": json.dumps({"functionList": light_functions}),
        },
        {
            "did": gateway_did,
            "sdid": "02ab3ca7076100000000000000000005",
            "spid": "00000000000000000000000032af0000",
            "devname": "红外设备自学习",
            "extend": "",
            "extendInfo": json.dumps({"functionList": learned_functions}),
        },
        {
            "did": gateway_did,
            "sdid": "02ab3ca7076100000000000000000001",
            "spid": "0000000000000000000000008fab0000",
            "devname": "空调方案",
            "extend": "{}",
        },
    ]

    _, light, learned, ac = parse_import_payload(_payload_for_devices(devices))[0].devices

    assert light.functions == {"on": 1, "white": 64}
    assert learned.rm_profile is RMProfile.LEARNED_IR
    assert learned.functions == {"红外开关": 1}
    assert ac.functions == {}
