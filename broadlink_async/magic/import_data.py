"""Magic Home family import payload parsing."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any

from .const import RM_MAX_PID
from .exceptions import ImportDataError
from .models import (
    DeviceKind,
    Family,
    ImportedDevice,
    ImportedGroup,
    ImportedScene,
    Room,
    VirtualSubToken,
    normalize_mac,
    normalize_pid,
    rm_profile_for_pid,
)


def _get(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def _string(value: object, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, (str, int, float)):
        raise ImportDataError("text field has an invalid type")
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ImportDataError("integer field has an invalid type")
    try:
        return int(str(value), 0)
    except ValueError as err:
        raise ImportDataError("integer field has an invalid value") from err


def _decode_mtag(value: object) -> object:
    if not isinstance(value, str) or not value:
        raise ImportDataError("mtag data must be a non-empty base64 string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise ImportDataError("invalid mtag base64 data") from err
    try:
        return json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ImportDataError("mtag data is not valid JSON") from err


def _parse_rooms(data: Mapping[str, Any]) -> list[Room]:
    room_list = _get(data, "roomlist", "roomList", default=[])
    if not isinstance(room_list, list):
        raise ImportDataError("family roomlist must be an array")
    rooms: list[Room] = []
    for item in room_list:
        if not isinstance(item, Mapping):
            continue
        room_id = _optional_int(_get(item, "roomId", "roomid", default=0))
        rooms.append(
            Room(
                room_id=room_id or 0,
                name=_string(_get(item, "roomName", "name", default="")),
            )
        )
    return rooms


def _parse_functions(data: Mapping[str, Any]) -> dict[str, int]:
    """Return RM child key names mapped to the command codes in functionList."""
    function_list: object = None
    for key in ("extend", "extendInfo"):
        extend = data.get(key)
        if isinstance(extend, str) and extend.strip():
            try:
                extend = json.loads(extend)
            except json.JSONDecodeError:
                continue
        if isinstance(extend, Mapping):
            function_list = _get(extend, "functionList", "functionlist")
            if isinstance(function_list, list):
                break
    if not isinstance(function_list, list):
        return {}
    functions: dict[str, int] = {}
    for item in function_list:
        if not isinstance(item, Mapping):
            continue
        function = _string(_get(item, "function")).strip()
        # Learned keys all use function "extend" and are told apart by name.
        name = _string(_get(item, "name")).strip() if function == "extend" else function
        try:
            code = _optional_int(_get(item, "type"))
        except ImportDataError:
            continue
        if name and code is not None and 0 <= code <= 0xFF:
            functions.setdefault(name, code)
    return functions


def _parse_channel_names(data: Mapping[str, Any]) -> list[str]:
    """Return switch key names from vGroups, indexed by channel."""
    groups = _get(data, "vGroups", "vgroups")
    if not isinstance(groups, list):
        return []
    names: dict[int, str] = {}
    for group in groups:
        if not isinstance(group, Mapping) or group.get("ignoreflag"):
            continue
        try:
            channel = _optional_int(_get(group, "channel"))
        except ImportDataError:
            continue
        if channel is not None and 0 <= channel <= 7:
            names.setdefault(channel, _string(_get(group, "name")).strip())
    if not names:
        return []
    return [names.get(channel, "") for channel in range(max(names) + 1)]


def _parse_device(data: Mapping[str, Any]) -> ImportedDevice:
    short_addr = _optional_int(_get(data, "shortaddr", "shortAddr"))
    devtype = _optional_int(_get(data, "devtype", "devType"))
    channel_names = _parse_channel_names(data)
    channel_count = (
        max(_optional_int(_get(data, "cnt", "channelCount")) or 0, len(channel_names))
        or 1
    )
    mac = normalize_mac(_string(_get(data, "mac", "deviceid", "deviceId")))
    return ImportedDevice(
        did=_string(_get(data, "did", "deviceid", "deviceId")),
        pid=_string(_get(data, "pid", "devpid", "devPid")),
        name=_string(_get(data, "devname", "name", default="BroadLink device")),
        mac=mac,
        sdid=_string(_get(data, "sdid")),
        spid=_string(_get(data, "spid")),
        short_addr=short_addr,
        ble_category=_string(_get(data, "blecatetory", "blecategory")),
        ble_device_type=_string(_get(data, "bledevtype")),
        devtype=devtype,
        room_id=_optional_int(_get(data, "roomId", "roomid")),
        token=_string(_get(data, "token", "aeskey", "aesKey")),
        bletoken=_string(_get(data, "bletoken")),
        version=_string(_get(data, "version")),
        channel_count=max(1, min(8, channel_count)),
        channel_names=channel_names,
        functions=_parse_functions(data),
        raw=dict(data),
    )


def mark_rm_children(devices: list[ImportedDevice]) -> None:
    """Associate RM children after a complete imported device list is available."""
    gateways_by_did: dict[str, list[ImportedDevice]] = {}
    for device in devices:
        if (
            normalize_pid(device.pid) == RM_MAX_PID
            and not device.sdid
            and device.ble_device_type.upper() != "GROUP"
        ):
            gateways_by_did.setdefault(device.did, []).append(device)

    for device in devices:
        if device.ble_device_type.upper() == "GROUP" or not device.sdid:
            continue
        normalized_sdid = (
            device.sdid.lower().replace(":", "").replace("-", "").replace("_", "")
        )
        for gateway in gateways_by_did.get(device.did, []):
            gateway_mac = normalize_mac(gateway.mac or gateway.did)
            if (
                gateway is not device
                and gateway_mac
                and normalized_sdid.startswith(gateway_mac)
            ):
                device.is_rm_child = True
                device.rm_profile = rm_profile_for_pid(device.spid)
                break


def _parse_virtual_subtokens(value: object) -> list[VirtualSubToken]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportDataError("vtsubtoken must be an array")
    result: list[VirtualSubToken] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ImportDataError("vtsubtoken entry must be an object")
        result.append(
            VirtualSubToken(
                did=_string(_get(item, "did")),
                pid=_string(_get(item, "pid")),
                token=_string(_get(item, "token")),
                type=_string(_get(item, "type")),
            )
        )
    return result


def _parse_group(data: Mapping[str, Any]) -> ImportedGroup:
    group_id = _optional_int(_get(data, "groupId", "groupid"))
    if group_id is None:
        raise ImportDataError("groupId is required")
    members = _get(data, "containDidList", "containDidlist", default=[])
    if not isinstance(members, list):
        members = []
    return ImportedGroup(
        group_id=group_id,
        name=_string(_get(data, "groupName", "name", default=f"Group {group_id}")),
        ble_category=_string(_get(data, "blecatetory", "blecategory")),
        room_id=_optional_int(_get(data, "roomId", "roomid")),
        room_name=_string(_get(data, "roomName", "room")),
        member_ids=[_string(member) for member in members],
    )


def _parse_scene(data: Mapping[str, Any]) -> ImportedScene:
    scene_id = _string(_get(data, "moduleid", "sceneId", "sceneid"))
    if not scene_id:
        raise ImportDataError("scene moduleid is required")
    modules = _get(data, "moduledev", default=[])
    if not isinstance(modules, list):
        modules = []
    return ImportedScene(
        scene_id=scene_id,
        name=_string(_get(data, "name", default=f"Scene {scene_id}")),
        room_id=_optional_int(_get(data, "roomId", "roomid")),
        room_name=_string(_get(data, "room", "roomName")),
        module_devices=[
            dict(module) for module in modules if isinstance(module, Mapping)
        ],
    )


def parse_import_payload(body: bytes) -> list[Family]:
    """Parse the Magic Home family import request body.

    Every malformed body raises ImportDataError, whose message never contains
    values from the body.
    """
    try:
        return _parse_import_payload(body)
    except ImportDataError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise ImportDataError("import body has an unexpected structure") from err


def _parse_import_payload(body: bytes) -> list[Family]:
    if not body:
        raise ImportDataError("import body is empty")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ImportDataError("import body is not valid JSON") from err
    if not isinstance(payload, list) or not payload:
        raise ImportDataError("import body must be a non-empty array")

    families: list[Family] = []
    for bundle in payload:
        if not isinstance(bundle, Mapping):
            raise ImportDataError("family import entry must be an object")
        family_id = _string(_get(bundle, "did"))
        if not family_id:
            raise ImportDataError("family did is required")

        family_info: Mapping[str, Any] = {}
        devices: list[ImportedDevice] = []
        groups: list[ImportedGroup] = []
        scenes: list[ImportedScene] = []
        data_list = _get(bundle, "dataList", "datalist", default=[])
        if not isinstance(data_list, list):
            raise ImportDataError("dataList must be an array")
        for mtag_entry in data_list:
            if not isinstance(mtag_entry, Mapping):
                raise ImportDataError("dataList entry must be an object")
            mtag = _string(_get(mtag_entry, "mtag"))
            decoded = _decode_mtag(_get(mtag_entry, "data"))
            if mtag == "familyInfo":
                if not isinstance(decoded, Mapping):
                    raise ImportDataError("familyInfo must decode to an object")
                family_info = decoded
            elif mtag == "devlist":
                if not isinstance(decoded, list):
                    raise ImportDataError("devlist must decode to an array")
                devices = [
                    _parse_device(item) for item in decoded if isinstance(item, Mapping)
                ]
            elif mtag == "grouplist":
                if not isinstance(decoded, list):
                    raise ImportDataError("grouplist must decode to an array")
                for item in decoded:
                    if not isinstance(item, Mapping):
                        continue
                    try:
                        groups.append(_parse_group(item))
                    except ImportDataError:
                        continue
            elif mtag == "scenelist":
                if not isinstance(decoded, list):
                    raise ImportDataError("scenelist must decode to an array")
                for item in decoded:
                    if not isinstance(item, Mapping):
                        continue
                    try:
                        scenes.append(_parse_scene(item))
                    except ImportDataError:
                        continue

        mark_rm_children(devices)
        for device in devices:
            if device.kind is DeviceKind.GATEWAY and not device.mac:
                device.mac = normalize_mac(device.did)
        bletoken = _string(
            _get(family_info, "bletoken", "bleToken", default=bundle.get("token", ""))
        ).strip()
        try:
            token = bytes.fromhex(bletoken)
        except ValueError as err:
            raise ImportDataError("family bletoken must be hexadecimal") from err
        if not token:
            raise ImportDataError("family bletoken is required")
        families.append(
            Family(
                family_id=family_id,
                name=_string(_get(family_info, "name", default=family_id)),
                bletoken=bletoken,
                pid=_string(_get(bundle, "pid")),
                token=_string(_get(bundle, "token")),
                rooms=_parse_rooms(family_info),
                devices=devices,
                groups=groups,
                scenes=scenes,
                virtual_subtokens=_parse_virtual_subtokens(_get(bundle, "vtsubtoken")),
            )
        )
    return families
