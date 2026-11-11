"""FastCon command framing used by RM Max gateways."""

from __future__ import annotations

from .exceptions import ProtocolError

FASTCON_FRAME_LENGTH = 22
FASTCON_TYPE_CONTROL_REQUEST = 5
FASTCON_TLV_TYPE_CONTROL = 2


def fastcon_checksum(frame: bytes | bytearray) -> int:
    """Return the FastCon checksum, excluding the checksum byte itself."""
    return sum(value for index, value in enumerate(frame) if index != 3) & 0xFF


def device_control(
    short_addr: int,
    command: bytes,
    *,
    seq: int,
    source_addr: int,
) -> bytes:
    """Build a 22-byte FastCon device-control frame."""
    if not 0 <= short_addr <= 0xFFFF:
        raise ProtocolError("short address must fit in uint16")
    if not command or len(command) > 14:
        raise ProtocolError("command length must be between 1 and 14 bytes")

    frame = bytearray(FASTCON_FRAME_LENGTH)
    high_addr = (short_addr >> 8) & 0x0F
    frame[0] = 0x80 | ((FASTCON_TYPE_CONTROL_REQUEST & 0x07) << 4) | high_addr
    frame[1] = seq & 0xFF
    frame[2] = source_addr & 0xFF
    frame[4] = FASTCON_TLV_TYPE_CONTROL | (((len(command) + 1) & 0x0F) << 4)
    frame[5] = short_addr & 0xFF
    frame[6 : 6 + len(command)] = command
    frame[3] = fastcon_checksum(frame)
    return bytes(frame)


def scene_control(
    scene_id: int,
    *,
    seq: int,
    source_addr: int,
) -> bytes:
    """Build a 22-byte FastCon scene-control frame."""
    if not 0 <= scene_id <= 0xFFFFFF:
        raise ProtocolError("scene ID must fit in 24 bits")
    frame = bytearray(FASTCON_FRAME_LENGTH)
    frame[0] = 0x80 | ((FASTCON_TYPE_CONTROL_REQUEST & 0x07) << 4)
    frame[1] = seq & 0xFF
    frame[2] = source_addr & 0xFF
    frame[4] = 0x3B
    frame[5] = (scene_id >> 16) & 0xFF
    frame[6] = 0
    frame[7] = scene_id & 0xFF
    frame[8] = (scene_id >> 8) & 0xFF
    frame[3] = fastcon_checksum(frame)
    return bytes(frame)


def apply_family_token(frame: bytes, bletoken: str) -> bytes:
    """Apply the family token source address and recalculate the checksum.

    This matches ``fastcon_passthough_pkt``: the final token byte replaces
    packet byte 2 and packet byte 3 is recalculated over all other bytes.
    """
    try:
        token = bytes.fromhex(bletoken.strip())
    except ValueError as err:
        raise ProtocolError("bletoken must be hexadecimal") from err
    if not token:
        raise ProtocolError("bletoken must not be empty")
    if len(frame) <= 3:
        return frame
    output = bytearray(frame)
    output[2] = token[-1]
    output[3] = fastcon_checksum(output)
    return bytes(output)
