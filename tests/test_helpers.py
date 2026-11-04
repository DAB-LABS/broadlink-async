"""Pure helpers: pulse packing, CRC16 and the protocol datetime."""

from __future__ import annotations

import datetime as dt

import pytest

from broadlink_async.helpers import CRC16
from broadlink_async.protocol import Datetime
from broadlink_async.remote import (
    _IR_TRAILING_GAP_TICKS,
    TICK,
    SignalKind,
    data_to_pulses,
    pulses_to_data,
)


def test_tick_constant():
    # 32768 Hz timebase: protocol.md's "us * 269 / 8192".
    assert TICK == pytest.approx(8192 / 269)
    assert TICK == pytest.approx(30.4535, abs=1e-4)


def test_pulses_to_data_header_and_short_pulses():
    data = pulses_to_data([328, 656])
    assert data[0] == 0x26
    assert data[1] == 0x00
    assert int.from_bytes(data[2:4], "little") == 2
    # round(328/30.4535)=11, round(656/30.4535)=22
    assert data[4:] == bytes([11, 22])


def test_pulses_to_data_rounds_to_nearest_tick():
    # 0.6 of a tick rounds up; 0.4 rounds down. The old code floored both.
    assert pulses_to_data([TICK * 10.6])[4] == 11
    assert pulses_to_data([TICK * 10.4])[4] == 10


def test_pulses_to_data_long_pulse_uses_three_byte_form():
    data = pulses_to_data([560, 10000])
    ticks = round(10000 / TICK)  # 328
    assert ticks > 255
    assert data[4:] == bytes([18, 0, ticks >> 8, ticks & 0xFF])
    assert int.from_bytes(data[2:4], "little") == 4


def test_explicit_tick_argument_still_honored():
    # Callers may still pass their own tick.
    assert pulses_to_data([328, 656], tick=32.84)[4:] == bytes([10, 20])
    assert data_to_pulses(bytes([0x26, 0, 1, 0, 10]), tick=32.84) == [328]


def test_data_to_pulses_round_trip_at_same_tick():
    pulses = [9000, 4500, 560, 560, 560, 1690, 560, 40000]
    data = pulses_to_data(pulses)
    back = data_to_pulses(data)
    # Rounding on the way in (and int() on the way out) keeps the round
    # trip within half a tick plus one microsecond.
    for a, b in zip(pulses, back, strict=True):
        assert abs(a - b) <= TICK / 2 + 1


def test_data_to_pulses_honors_declared_length():
    data = pulses_to_data([328, 656]) + b"\x0d\x05"  # trailing terminator bytes
    assert len(data_to_pulses(data)) == 2


GAP = bytes([0x00, 0x0D, 0x05])  # _IR_TRAILING_GAP_TICKS, as learned codes end


def test_ir_packet_ending_on_a_mark_gets_the_learned_code_gap():
    # Three durations: on, off, on. The device needs an off time after the
    # last on time (home-assistant/core#190257).
    data = pulses_to_data([328, 656, 328])
    assert _IR_TRAILING_GAP_TICKS == 3333
    assert data[4:] == bytes([11, 22, 11]) + GAP
    assert int.from_bytes(data[2:4], "little") == 6
    assert data_to_pulses(data)[-1] == int(_IR_TRAILING_GAP_TICKS * TICK)


def test_trailing_gap_with_kind_passed_as_an_int():
    assert pulses_to_data([328, 656, 328], kind=0x26).endswith(GAP)


def test_trailing_gap_accepts_any_sequence():
    assert pulses_to_data(iter([328, 656, 328])) == pulses_to_data([328, 656, 328])


def test_empty_ir_packet_gets_no_gap():
    assert pulses_to_data([]) == bytes([0x26, 0, 0, 0])


def test_ir_packet_ending_on_a_space_is_unchanged():
    assert pulses_to_data([328, 656, 328, 656]) == bytes([0x26, 0, 4, 0, 11, 22, 11, 22])


def test_rc6_frame_ends_with_the_gap():
    # Home Assistant's RC-6 encoder ends every frame on a mark: Philips TV
    # power, toggle 1, as infrared-protocols builds it.
    u = 444
    frame = [6 * u, -2 * u, u, -2 * u, u, -u, u, -u, 3 * u, -3 * u]
    frame += [u, -u] * 11 + [2 * u, -u, u, -2 * u, u, -u, u]
    data = pulses_to_data([abs(t) for t in frame])
    assert len(frame) % 2 == 1
    assert data.endswith(GAP)
    assert len(data_to_pulses(data)) == len(frame) + 1


def test_trailing_gap_keeps_the_repeat_byte():
    # A repeated frame needs the gap too, or the next copy's leader runs
    # into the last mark.
    data = pulses_to_data([328, 656, 328], repeat=1)
    assert data[:2] == bytes([0x26, 1])
    assert data.endswith(GAP)


def test_trailing_gap_is_in_device_ticks_whatever_the_tick():
    data = pulses_to_data([328, 656, 328], tick=32.84)
    assert data[4:] == bytes([10, 20, 10]) + GAP


def test_rf_packet_ending_on_a_mark_is_unchanged():
    data = pulses_to_data([328, 656, 328], kind=SignalKind.RF_433)
    assert data == bytes([0xB2, 0, 3, 0, 11, 22, 11])


def test_data_to_pulses_rejects_truncated_long_form():
    with pytest.raises(ValueError):
        data_to_pulses(bytes([0x26, 0x00, 0x02, 0x00, 0x00, 0x01]))


def test_crc16_known_vector():
    # CRC-16/MODBUS of "123456789" is 0x4B37.
    assert CRC16.calculate(b"123456789") == 0x4B37
    assert CRC16.calculate(b"") == 0xFFFF


def test_crc16_table_is_cached():
    CRC16._cache.pop(0xA001, None)
    t1 = CRC16.get_table(0xA001)
    t2 = CRC16.get_table(0xA001)
    assert t1 is t2
    assert len(t1) == 256


def test_datetime_pack_layout():
    tz = dt.timezone(dt.timedelta(hours=-7))
    when = dt.datetime(2026, 9, 4, 14, 30, 0, tzinfo=tz)
    data = Datetime.pack(when)
    assert len(data) == 12
    assert int.from_bytes(data[0:4], "little", signed=True) == -7
    assert int.from_bytes(data[4:6], "little") == 2026
    assert data[6] == 30
    assert data[7] == 14
    assert data[8] == 26
    assert data[9] == 5  # Friday
    assert data[10] == 4
    assert data[11] == 9


def test_datetime_round_trip_and_validation():
    tz = dt.timezone(dt.timedelta(hours=2))
    when = dt.datetime(2026, 1, 15, 8, 5, 0, tzinfo=tz)
    data = bytearray(Datetime.pack(when))
    assert Datetime.unpack(bytes(data)) == when
    data[9] = 1  # wrong weekday
    with pytest.raises(ValueError):
        Datetime.unpack(bytes(data))


def test_datetime_now_has_tzinfo():
    assert Datetime.now().tzinfo is not None
