"""Bluetooth light command encoding."""

from .exceptions import CommandError


def encode_light_power(on: bool) -> bytes:
    """Encode a light power command."""
    return b"\x80" if on else b"\x00"


def encode_light_brightness(brightness: int) -> bytes:
    """Encode Home Assistant brightness as the FastCon 0-127 value."""
    if not 0 <= brightness <= 255:
        raise CommandError("brightness must be between 0 and 255")
    value = round(brightness * 127 / 255)
    return bytes((value,))


def encode_rgbcw_light(
    *,
    on: bool,
    brightness: int = 255,
    rgb: tuple[int, int, int] | None = None,
    cold_percent: int | None = None,
) -> bytes:
    """Encode the six-byte RGBCW light profile used by EasyIndustry."""
    if not 0 <= brightness <= 255:
        raise CommandError("brightness must be between 0 and 255")
    if cold_percent is not None and not 0 <= cold_percent <= 100:
        raise CommandError("color temperature percent must be between 0 and 100")
    if rgb is not None and any(not 0 <= value <= 255 for value in rgb):
        raise CommandError("RGB values must be between 0 and 255")

    payload = bytearray(6)
    if not on:
        return bytes(payload)

    payload[0] = round(brightness * 127 / 255)
    if rgb is not None:
        red, green, blue = rgb
        payload[1] = blue
        payload[2] = red
        payload[3] = green
        if (red or green or blue) and payload[0] == 0:
            payload[0] = 0x80
    if cold_percent is not None:
        cold = round(cold_percent * 255 / 100)
        payload[4] = 255 - cold
        payload[5] = cold
    if payload[0] == 0 and rgb is None and cold_percent is None:
        payload[0] = 0x80
    return bytes(payload)
