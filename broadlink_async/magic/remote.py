"""TV and set-top box remote command encoding."""

from __future__ import annotations

from collections.abc import Mapping

from .exceptions import CommandError, ProtocolError
from .models import RMProfile

FUNCTION_KEYS: dict[str, int] = {
    "power": 0x01,
    "pwr": 0x01,
    "input": 0x02,
    "mute": 0x03,
    "tv_av": 0x04,
    "ok": 0x05,
    "1": 0x06,
    "2": 0x07,
    "3": 0x08,
    "4": 0x09,
    "5": 0x0A,
    "6": 0x0B,
    "7": 0x0C,
    "8": 0x0D,
    "9": 0x0E,
    "0": 0x0F,
    "playback": 0x10,
    "volume_up": 0x11,
    "volume_down": 0x12,
    "channel_up": 0x13,
    "channel_down": 0x14,
    "up": 0x15,
    "down": 0x16,
    "left": 0x17,
    "right": 0x18,
    "screen": 0x1B,
    "menu": 0x1C,
    "back": 0x1D,
    "home": 0x1E,
    "fast_forward": 0x1F,
    "fast_backward": 0x20,
    "pause": 0x21,
    "play": 0x22,
    "audio_mode": 0x27,
    "guide": 0x2A,
    "red": 0x2B,
    "green": 0x2C,
    "yellow": 0x2D,
    "blue": 0x2E,
    "help": 0x2F,
    "exit": 0x30,
    "fav": 0x32,
    "info": 0x33,
    "next": 0x34,
    "previous": 0x35,
    "stop": 0x36,
    "time": 0x37,
    "hdmi": 0x38,
    "computer": 0x39,
    "picture_mode": 0x3A,
    "zoom_in": 0x3B,
    "dot": 0x3C,
    "automatic": 0x3D,
}

_AV_PROFILES = {
    RMProfile.TV,
    RMProfile.STB,
    RMProfile.PROJECTOR,
    RMProfile.SMART_BOX,
    RMProfile.DVD,
    RMProfile.SPEAKER,
    RMProfile.AMPLIFIER,
}

PROFILE_COMMANDS: dict[RMProfile, dict[str, int]] = {
    **{profile: FUNCTION_KEYS for profile in _AV_PROFILES},
    RMProfile.CURTAIN: {
        "open": 0x01,
        "close": 0x02,
        "stop": 0x03,
        "forward": 0x04,
        "reverse": 0x05,
    },
    RMProfile.RELAY_PANEL: {
        "channel_1_off": 0x10,
        "channel_1_on": 0x11,
        "channel_2_off": 0x20,
        "channel_2_on": 0x21,
        "channel_3_off": 0x30,
        "channel_3_on": 0x31,
        "all_off": 0xF0,
        "off_on": 0xF1,
    },
    RMProfile.FAN: {
        "power": 0x01,
        "oscillate": 0x02,
        "wind_type": 0x03,
        "speed": 0x04,
        "speed_up": 0x05,
        "speed_down": 0x06,
        "timer": 0x37,
    },
    RMProfile.RM_LIGHT: {
        "turn_on": 0x01,
        "turn_off": 0x02,
        "brightness_up": 0x03,
        "brightness_down": 0x04,
        "blink": 0x05,
        "strobe": 0x06,
        "gradient": 0x07,
        "soft": 0x08,
        "red": 0x2B,
        "green": 0x2C,
        "yellow": 0x2D,
        "blue": 0x2E,
    },
    RMProfile.DRYING_RACK: {
        "up": 0x01,
        "down": 0x02,
        "stop": 0x03,
        "air_dry": 0x04,
        "heat_dry": 0x05,
        "sterilize": 0x06,
        "light_on": 0x07,
        "light_off": 0x08,
    },
    RMProfile.PURIFIER: {
        "power": 0x01,
        "auto": 0x3D,
        "timer": 0x37,
        "speed": 0x38,
        "sleep": 0x39,
    },
    RMProfile.WATER_HEATER: {
        "power": 0x01,
        "temperature_down": 0x02,
        "temperature_up": 0x03,
        "schedule": 0x04,
        "keep_warm": 0x05,
    },
    RMProfile.HUMIDIFIER: {
        "power": 0x01,
        "level": 0x08,
        "timer": 0x37,
        "speed": 0x38,
        "sleep": 0x39,
    },
    RMProfile.VACUUM: {
        "power": 0x01,
        "timer": 0x37,
        "charge": 0x3B,
        "auto": 0x3D,
    },
}


def encode_key(command: str) -> bytes:
    """Encode one TV/STB remote key."""
    key = command.strip().lower()
    try:
        return bytes((FUNCTION_KEYS[key],))
    except KeyError as err:
        raise CommandError(f"unsupported remote command: {command}") from err


def encode_step(kind: str, step: int) -> list[bytes]:
    """Encode volume or channel step commands including follow frames."""
    if kind not in {"volume", "channel"}:
        raise CommandError(f"unsupported step kind: {kind}")
    key = f"{kind}_{'up' if step > 0 else 'down'}"
    return [encode_key(key) for _ in range(max(1, abs(step)))]


def encode_channel(channel: str | int, *, supports_digits: bool = False) -> list[bytes]:
    """Encode a channel number."""
    value = str(channel)
    if not value or any(character not in "0123456789" for character in value):
        raise CommandError(f"invalid channel number: {channel}")
    frames = [encode_key(character) for character in value]
    if supports_digits:
        return [b"".join(frames)]
    return frames


def encode_commands(commands: list[str]) -> list[bytes]:
    """Encode a sequence of named remote commands."""
    if not commands:
        raise CommandError("at least one remote command is required")
    return [encode_key(command) for command in commands]


FUNCTION_ALIASES: dict[str, tuple[str, ...]] = {
    "turn_on": ("on",),
    "turn_off": ("off",),
    "brightness_up": ("bright",),
    "brightness_down": ("dim",),
    "blink": ("flash",),
    "gradient": ("fade",),
    "soft": ("smooth",),
    "open": ("motor_open", "motor_up"),
    "close": ("motor_close", "motor_down"),
    "stop": ("motor_pause", "motor_stop", "dry_stop", "dry_pause"),
    "up": ("dry_up", "motor_up"),
    "down": ("dry_down", "motor_down"),
    "speed": ("windspeed",),
    "auto": ("automatic",),
    "temperature_up": ("temperature_increase",),
    "temperature_down": ("temperature_decrease",),
    **{
        f"channel_{channel}_{state}": (f"switch{channel}_{action}",)
        for channel in (1, 2, 3)
        for state, action in (("on", "open"), ("off", "close"))
    },
    "all_on": ("switch_all_open",),
    "off_on": ("switch_all_open",),
    "all_off": ("switch_all_close",),
}


def _imported_code(functions: Mapping[str, int], command: str) -> int | None:
    by_name = {name.strip().lower(): code for name, code in functions.items()}
    key = command.strip().lower()
    for name in (key, *FUNCTION_ALIASES.get(key, ())):
        if name in by_name:
            return by_name[name]
    return None


def encode_profile_commands(
    profile: RMProfile,
    commands: list[str],
    functions: Mapping[str, int] | None = None,
) -> list[bytes]:
    """Encode named commands for an RM child profile.

    When the imported functionList is available its codes are authoritative and
    only its keys are accepted; the built-in tables cover older imports.
    """
    if not commands:
        raise CommandError("at least one profile command is required")
    if functions:
        frames: list[bytes] = []
        for command in commands:
            code = _imported_code(functions, command)
            if code is None:
                raise CommandError(f"unsupported {profile.value} command: {command}")
            frames.append(bytes((code,)))
        return frames
    if profile in {RMProfile.LEARNED_IR, RMProfile.LEARNED_RF}:
        raise ProtocolError(f"{profile.value} has no imported learned keys")
    command_table = PROFILE_COMMANDS.get(profile)
    if command_table is None:
        raise ProtocolError(f"command encoding is not supported for {profile.value}")

    frames = []
    for command in commands:
        key = command.strip().lower()
        try:
            frames.append(bytes((command_table[key],)))
        except KeyError as err:
            raise CommandError(f"unsupported {profile.value} command: {command}") from err
    return frames


def supports_profile_command(
    profile: RMProfile,
    command: str,
    functions: Mapping[str, int] | None = None,
) -> bool:
    """Return whether an RM child profile can encode a named command."""
    try:
        encode_profile_commands(profile, [command], functions)
    except (CommandError, ProtocolError):
        return False
    return True
