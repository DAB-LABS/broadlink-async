"""RM Max air-conditioner command encoding."""

from .exceptions import CommandError

AC_MODE_AUTO = 0
AC_MODE_HEAT = 1
AC_MODE_COOL = 2
AC_MODE_FAN = 4
AC_MODE_DRY = 8

AC_FAN_AUTO = 0
AC_FAN_LOW = 1
AC_FAN_MEDIUM = 2
AC_FAN_HIGH = 3

FLOOR_HEATING_MIN_TEMP = 16
FLOOR_HEATING_MAX_TEMP = 45

FRESH_AIR_MODE_FRESH = 1
FRESH_AIR_MODE_COOL = 2
FRESH_AIR_MODE_SMART = 3
FRESH_AIR_MODE_TURBO = 4
FRESH_AIR_MODE_SLEEP = 5
FRESH_AIR_MODE_PURIFY = 6

FRESH_AIR_FAN_LOW = 1
FRESH_AIR_FAN_MEDIUM = 2
FRESH_AIR_FAN_HIGH = 3
FRESH_AIR_FAN_MEDIUM_LOW = 4
FRESH_AIR_FAN_MEDIUM_HIGH = 5

# Three-in-one panels share function code 0x00 for all power switches; bits 1-2
# select the floor-heating or fresh-air load and bit 0 carries the state.
_FLOOR_HEATING_POWER = (0x02, 0x03)
_FRESH_AIR_POWER = (0x04, 0x05)

_ATTRIBUTE_INDEX = {
    "power": 0,
    "mode": 1,
    "temperature": 2,
    "fan": 3,
}


def encode_ac_attribute(attribute: str, value: int) -> bytes:
    """Encode one AC attribute as the three-byte RM Max TLV."""
    try:
        index = _ATTRIBUTE_INDEX[attribute]
    except KeyError as err:
        raise CommandError(f"unsupported AC attribute: {attribute}") from err

    if attribute == "power" and value not in {0, 1}:
        raise CommandError("AC power must be 0 or 1")
    if attribute == "mode" and value not in {
        AC_MODE_AUTO,
        AC_MODE_HEAT,
        AC_MODE_COOL,
        AC_MODE_FAN,
        AC_MODE_DRY,
    }:
        raise CommandError("unsupported AC mode")
    if attribute == "temperature" and not 16 <= value <= 30:
        raise CommandError("AC temperature must be between 16 and 30")
    if attribute == "fan" and value not in {
        AC_FAN_AUTO,
        AC_FAN_LOW,
        AC_FAN_MEDIUM,
        AC_FAN_HIGH,
    }:
        raise CommandError("unsupported AC fan mode")
    return bytes((index, 1, value))


def encode_floor_heating_attribute(attribute: str, value: int) -> bytes:
    """Encode one three-in-one floor-heating attribute."""
    if attribute == "power":
        if value not in {0, 1}:
            raise CommandError("floor heating power must be 0 or 1")
        return bytes((0x00, 1, _FLOOR_HEATING_POWER[value]))
    if attribute == "temperature":
        if not FLOOR_HEATING_MIN_TEMP <= value <= FLOOR_HEATING_MAX_TEMP:
            raise CommandError(
                f"floor heating temperature must be between "
                f"{FLOOR_HEATING_MIN_TEMP} and {FLOOR_HEATING_MAX_TEMP}"
            )
        return bytes((0x04, 1, value))
    raise CommandError(f"unsupported floor heating attribute: {attribute}")


def encode_fresh_air_attribute(attribute: str, value: int) -> bytes:
    """Encode one three-in-one fresh-air attribute."""
    if attribute == "power":
        if value not in {0, 1}:
            raise CommandError("fresh air power must be 0 or 1")
        return bytes((0x00, 1, _FRESH_AIR_POWER[value]))
    if attribute == "mode":
        if not FRESH_AIR_MODE_FRESH <= value <= FRESH_AIR_MODE_PURIFY:
            raise CommandError("unsupported fresh air mode")
        return bytes((0x01, 1, value << 4))
    if attribute == "fan":
        if not FRESH_AIR_FAN_LOW <= value <= FRESH_AIR_FAN_MEDIUM_HIGH:
            raise CommandError("unsupported fresh air fan speed")
        return bytes((0x03, 1, value << 4))
    raise CommandError(f"unsupported fresh air attribute: {attribute}")
