"""Industry vectors for switch panels, curtains, and status queries."""

import pytest

from broadlink_async.magic import (
    CURTAIN_CLOSE,
    CURTAIN_OPEN,
    CURTAIN_STOP,
    MSG_STATUS_QUERY,
    ProtocolError,
    encode_curtain_backlight,
    encode_curtain_limit,
    encode_curtain_motion,
    encode_curtain_position,
    encode_curtain_switch,
    encode_switch_channel,
    pack_status_query,
    unpack_header,
)


def test_switch_channel_vectors() -> None:
    assert encode_switch_channel(0, True) == b"\x01\x01"
    assert encode_switch_channel(3, False) == b"\x08\x00"
    with pytest.raises(ProtocolError):
        encode_switch_channel(8, True)


def test_curtain_motion_and_position_vectors() -> None:
    assert encode_curtain_motion(CURTAIN_OPEN) == b"\x01\xff\x00\xff\x00\x00"
    assert encode_curtain_motion(CURTAIN_CLOSE) == b"\x02\xff\x00\xff\x00\x00"
    assert encode_curtain_motion(CURTAIN_STOP, motor=2) == (b"\x00\xff\x00\xff\x00\x06")
    assert encode_curtain_position(75) == b"\x00\x4b\x00\xff\x00\x00"
    assert encode_curtain_position(25, motor=2) == b"\x00\xff\x00\x19\x00\x00"
    assert encode_curtain_limit(10) == b"\x00\xff\x00\xff\x0a\x00"
    assert encode_curtain_backlight(True) == b"\x80"
    assert encode_curtain_switch(2, True) == b"\x02\x02"


def test_status_query_matches_industry_vector() -> None:
    packet = pack_status_query([257], sequence=1)
    assert unpack_header(packet) == (MSG_STATUS_QUERY, 1)
    assert packet.hex() == "1100010000010101000000000000000000000000"
