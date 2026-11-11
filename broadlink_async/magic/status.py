"""FastCon status report parsing."""

from dataclasses import dataclass

from .fastcon import fastcon_checksum
from .models import DeviceKind, ImportedDevice


@dataclass(slots=True, frozen=True)
class FastConReport:
    """A decoded FastCon device report."""

    short_addr: int
    command: bytes


def parse_fastcon_report(frame: bytes) -> FastConReport | None:
    """Parse a FastCon single-device frame."""
    if len(frame) < 6 or ((frame[0] >> 4) & 0x07) != 5:
        return None
    if fastcon_checksum(frame) != frame[3]:
        return None
    tlv_type = frame[4] & 0x0F
    tlv_length = (frame[4] >> 4) & 0x0F
    if tlv_type != 2 or tlv_length < 1:
        return None
    command_length = tlv_length - 1
    if len(frame) < 6 + command_length:
        return None
    short_addr = ((frame[0] & 0x0F) << 8) | frame[5]
    return FastConReport(
        short_addr=short_addr,
        command=bytes(frame[6 : 6 + command_length]),
    )


def parse_device_upload(
    device: ImportedDevice,
    payload: bytes,
) -> dict[str, object]:
    """Decode an EasyIndustry device upload into normalized state values."""
    if device.kind is DeviceKind.AC and device.is_three_in_one:
        return _parse_three_in_one_upload(payload)

    if device.kind is DeviceKind.AC:
        if len(payload) < 4:
            return {}
        return {
            "power": payload[0],
            "mode": payload[1],
            "temperature": payload[2],
            "fan": payload[3],
        }

    if device.kind is DeviceKind.LIGHT and payload:
        values: dict[str, object] = {
            "is_on": payload[0] != 0,
        }
        brightness = payload[0] & 0x7F
        if payload[0] == 0:
            values["brightness"] = 0
        else:
            brightness_percent = max(1, brightness * 100 // 127)
            values["brightness"] = round(brightness_percent * 255 / 100)
        if len(payload) >= 4:
            values["rgb_color"] = (payload[2], payload[3], payload[1])
        if len(payload) >= 6:
            color_temp_percent = payload[5] * 100 // 255
            values["color_temp_kelvin"] = round(
                2700 + color_temp_percent * (6500 - 2700) / 100
            )
        return values

    if device.kind in {DeviceKind.SWITCH, DeviceKind.PLUG}:
        if len(payload) < 2:
            return {}
        set_mask, value_mask = payload[:2]
        channels = {
            channel: bool(value_mask & (1 << channel))
            for channel in range(8)
            if set_mask & (1 << channel)
        }
        return {"channels": channels} if channels else {}

    if device.kind is DeviceKind.CURTAIN:
        # Byte1 is the first-travel percentage (androidsdk curtain_screentargetpos);
        # 0xff until travel limits are set, when byte0 only echoes the last command.
        # While moving, byte1 is the start position and byte0 is 1 (open) or 2 (close).
        if len(payload) < 2 or payload[1] > 100:
            return {}
        motion = {1: "opening", 2: "closing"}.get(payload[0], "stopped")
        return {"position": payload[1], "motion": motion}

    return {}


_THREE_IN_ONE_STATUS_LENGTH = 15
_AC_MODES = frozenset({0, 1, 2, 4, 8})


def _parse_three_in_one_upload(payload: bytes) -> dict[str, object]:
    """Decode a kvgo bbaf three-in-one thermostat status frame.

    The panel also uploads its capability frame (temperature limits, load
    types) through the same channel, sometimes zero-padded to 15 bytes. Bits 3
    and 7 of the power byte are never set in a status frame, while the AC
    temperature limit stored there in a capability frame normally sets bit 3.
    """
    if len(payload) != _THREE_IN_ONE_STATUS_LENGTH:
        return {}
    power, mode, temperature, speed = payload[:4]
    if power & 0x88 or mode & 0x0F not in _AC_MODES or not 5 <= temperature <= 45:
        return {}
    return {
        "power": power & 0x01,
        "mode": mode & 0x0F,
        "temperature": temperature,
        "fan": speed & 0x0F,
        "current_temperature": int.from_bytes(payload[5:6], signed=True),
        "floor_heating_power": (power >> 1) & 0x01,
        "floor_heating_temperature": payload[6],
        "fresh_air_power": (power >> 2) & 0x01,
        "fresh_air_mode": mode >> 4,
        "fresh_air_fan": speed >> 4,
    }


def parse_device_status(
    device: ImportedDevice,
    command: bytes,
) -> dict[str, object]:
    """Backward-compatible alias for EasyIndustry upload decoding."""
    return parse_device_upload(device, command)
