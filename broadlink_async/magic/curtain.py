"""EasyIndustry and kvgo-compatible curtain control payloads."""

from .exceptions import ProtocolError

CURTAIN_OPEN = 1
CURTAIN_CLOSE = 2
CURTAIN_STOP = 3


def _profile() -> bytearray:
    payload = bytearray(6)
    payload[1] = 0xFF
    payload[3] = 0xFF
    return payload


def encode_curtain_motion(action: int, *, motor: int = 1) -> bytes:
    """Encode open, close, or stop for one curtain motor."""
    if action not in {CURTAIN_OPEN, CURTAIN_CLOSE, CURTAIN_STOP}:
        raise ProtocolError("curtain action must be open, close, or stop")
    if motor not in {1, 2}:
        raise ProtocolError("curtain motor must be 1 or 2")
    payload = _profile()
    if motor == 1:
        payload[0] = action
    else:
        payload[5] = action << 1
    return bytes(payload)


def encode_curtain_position(position: int, *, motor: int = 1) -> bytes:
    """Encode a 0..100 target position for one curtain motor."""
    if not 0 <= position <= 100:
        raise ProtocolError("curtain position must be between 0 and 100")
    if motor not in {1, 2}:
        raise ProtocolError("curtain motor must be 1 or 2")
    payload = _profile()
    if motor == 1:
        payload[1] = position
    else:
        payload[3] = position
    return bytes(payload)


def encode_curtain_limit(value: int) -> bytes:
    """Encode the kvgo curtain_limit profile."""
    if not 0 <= value <= 0x0F:
        raise ProtocolError("curtain limit must fit in four bits")
    payload = _profile()
    payload[4] = value
    return bytes(payload)


def encode_curtain_backlight(on: bool) -> bytes:
    """Encode the kvgo backlight command passed to device_control."""
    return bytes((0x80 if on else 0,))


def encode_curtain_switch(channel: int, on: bool) -> bytes:
    """Encode the pwrN compatibility path used by curtain panels."""
    if not 1 <= channel <= 8:
        raise ProtocolError("curtain switch channel must be between 1 and 8")
    mask = 1 << (channel - 1)
    return bytes((mask, mask if on else 0))
