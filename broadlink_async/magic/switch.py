"""EasyIndustry-compatible switch and plug control encoding."""

from .exceptions import ProtocolError


def encode_switch_channel(channel: int, on: bool) -> bytes:
    """Encode one SWITCH/PLUG channel update."""
    if not 0 <= channel <= 7:
        raise ProtocolError("switch channel must be between 0 and 7")
    mask = 1 << channel
    return bytes((mask, mask if on else 0))
