"""Building RM4 Pro RF packets (type 0xB1) that carry their own carrier.

The fixture is from an RM4 Pro bench (firmware 52079, 2026-11-13): one
frame each of a plug's On and Off codes, the six packets built from them
that were sent (with what the plug did), and two packets the device
returned from learning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from broadlink_async.remote import (
    RM4_RF_TYPE,
    TICK,
    SignalKind,
    data_to_pulses,
    parse_packet,
    pulses_to_data,
    pulses_to_rm4_rf,
    realign_rf_packet,
    rf_carrier_mhz,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rm4pro_rf_bench.json"
BENCH = json.loads(FIXTURE.read_text())
ON = BENCH["frames"]["on"]
BUILT = BENCH["built"]
LEARNED = {name: bytes.fromhex(packet) for name, packet in BENCH["learned"].items()}

GAP = 12881
TAIL = 45680


def signed(durations: list[int]) -> list[int]:
    """Unsigned durations, starting with a pulse, as signed timings."""
    return [d if i % 2 == 0 else -d for i, d in enumerate(durations)]


@pytest.mark.parametrize("name", sorted(BUILT))
def test_matches_the_packets_sent_on_the_bench(name):
    sent = BUILT[name]
    packet = pulses_to_rm4_rf(
        BENCH["frames"][sent["frame"]],
        sent["carrier_khz"] / 1000,
        frames=sent["frames"],
        gap_us=GAP,
        tail_us=TAIL,
    )
    assert packet == bytes.fromhex(sent["packet"])


def test_header():
    packet = pulses_to_rm4_rf([328, -656], 433.42)
    assert packet[0] == RM4_RF_TYPE == 0xB1
    assert packet[1] == 0xC0
    assert int.from_bytes(packet[2:4], "little") == len(packet) - 4
    assert int.from_bytes(packet[4:8], "little") == 433420
    assert packet[8:] == bytes([11, 22])


def test_carrier_reads_back():
    for mhz in (433.0, 433.42, 433.92, 434.79, 315.0):
        assert rf_carrier_mhz(pulses_to_rm4_rf([328, -656], mhz)) == mhz


@pytest.mark.parametrize("name", sorted(LEARNED))
def test_learned_packet_reads_back_through_the_builder(name):
    # A learned packet's own timings rebuild it byte for byte.
    packet = LEARNED[name]
    assert len(packet) == 530
    rebuilt = pulses_to_rm4_rf(signed(data_to_pulses(packet)), rf_carrier_mhz(packet))
    assert rebuilt == packet


def test_round_trip_through_parse_packet():
    packet = pulses_to_rm4_rf(ON, 433.92, frames=4, gap_us=GAP, tail_us=TAIL)
    parsed = parse_packet(packet)
    assert parsed.kind is SignalKind.RF_433
    assert parsed.type_byte == 0xB1
    assert parsed.frequency_mhz == 433.92
    assert len(parsed.pulses) == 4 * (len(ON) + 1)
    frame = [abs(t) for t in ON] + [GAP]
    expected = frame * 3 + frame[:-1] + [TAIL]
    for a, b in zip(parsed.pulses, expected, strict=True):
        assert abs(a - b) <= TICK / 2 + 1


def test_frame_ending_on_an_off_time_keeps_it_as_the_gap():
    packet = pulses_to_rm4_rf([328, -656, 328, -9000], 433.92, frames=2)
    gap = round(9000 / TICK)
    long = bytes([0, gap >> 8, gap & 0xFF])
    assert packet[8:] == bytes([11, 22, 11]) + long + bytes([11, 22, 11]) + long


def test_gap_us_replaces_a_trailing_off_time():
    with_gap = pulses_to_rm4_rf([328, -656, 328, -9000], 433.92, frames=2, gap_us=656)
    assert with_gap[8:] == bytes([11, 22, 11, 22]) * 2


def test_frame_ending_on_a_pulse_needs_gap_us():
    with pytest.raises(ValueError, match="gap_us"):
        pulses_to_rm4_rf([328, -656, 328], 433.92)
    packet = pulses_to_rm4_rf([328, -656, 328], 433.92, frames=2, gap_us=656)
    assert packet[8:] == bytes([11, 22, 11, 22]) * 2


def test_the_packet_always_ends_on_an_off_time():
    packet = pulses_to_rm4_rf([328], 433.92, gap_us=656)
    assert data_to_pulses(packet) == [int(11 * TICK), int(22 * TICK)]


def test_tail_us_is_the_last_off_time_only():
    packet = pulses_to_rm4_rf([328, -656], 433.92, frames=3, tail_us=984)
    assert packet[8:] == bytes([11, 22, 11, 22, 11, 32])


def test_one_frame_is_written_as_one_frame():
    # The library writes the frames it is given; any floor is the caller's.
    packet = pulses_to_rm4_rf(ON, 433.92, gap_us=GAP, tail_us=TAIL)
    assert len(data_to_pulses(packet)) == len(ON) + 1


def test_explicit_tick():
    packet = pulses_to_rm4_rf([328, -656], 433.92, tick=32.84)
    assert packet[8:] == bytes([10, 20])


def test_no_size_limit_below_the_length_field():
    packet = pulses_to_rm4_rf(ON, 433.92, frames=20, gap_us=GAP, tail_us=TAIL)
    assert len(packet) == 1048
    assert len(data_to_pulses(packet)) == 20 * (len(ON) + 1)


def test_refuses_a_packet_too_long_for_its_length_field():
    with pytest.raises(ValueError, match="length field"):
        pulses_to_rm4_rf([328, -656], 433.92, frames=40_000)


@pytest.mark.parametrize(
    "timings",
    [
        pytest.param([], id="empty"),
        pytest.param([-328, 656], id="starts_on_an_off_time"),
        pytest.param([0, -656], id="starts_on_zero"),
        pytest.param([328, 656], id="two_pulses"),
        pytest.param([328, -656, -328], id="two_off_times"),
        pytest.param([328, 0, 328], id="zero_in_the_middle"),
    ],
)
def test_refuses_timings_that_do_not_alternate(timings):
    with pytest.raises(ValueError, match="RF timings"):
        pulses_to_rm4_rf(timings, 433.92, gap_us=GAP)


@pytest.mark.parametrize("frames", [0, -1])
def test_refuses_fewer_than_one_frame(frames):
    with pytest.raises(ValueError, match="frames"):
        pulses_to_rm4_rf([328, -656], 433.92, frames=frames)


@pytest.mark.parametrize(
    "carrier", [0, 0.0004, -433.92, float("nan"), float("inf"), 4_294_968]
)
def test_refuses_a_carrier_that_does_not_fit(carrier):
    with pytest.raises(ValueError, match="carrier"):
        pulses_to_rm4_rf([328, -656], carrier)


def test_does_not_check_bands():
    # 433.00 MHz is outside Home Assistant's declared range but the device
    # sends it; bands are the caller's business.
    assert rf_carrier_mhz(pulses_to_rm4_rf([328, -656], 433.0)) == 433.0


@pytest.mark.parametrize(("gap_us", "tail_us"), [(0, None), (-1, None), (None, 0)])
def test_refuses_a_gap_or_tail_that_is_not_positive(gap_us, tail_us):
    with pytest.raises(ValueError, match="must be positive"):
        pulses_to_rm4_rf([328, -656], 433.92, gap_us=gap_us, tail_us=tail_us)


# The shared tick encoder, used by pulses_to_data and pulses_to_rm4_rf.


def test_a_duration_under_half_a_tick_is_written_as_one_tick():
    # A lone 0x00 would start the long form and swallow the next two bytes.
    data = pulses_to_data([328, 10, 328, 656])
    assert data[4:] == bytes([11, 1, 11, 22])
    assert len(data_to_pulses(data)) == 4
    packet = pulses_to_rm4_rf([328, -10, 328, -656], 433.92)
    assert packet[8:] == bytes([11, 1, 11, 22])
    assert len(data_to_pulses(packet)) == 4


def test_the_longest_duration_still_fits():
    assert pulses_to_data([328, 0xFFFF * TICK])[4:] == bytes([11, 0, 0xFF, 0xFF])


@pytest.mark.parametrize("us", [65536 * TICK, 3_000_000])
def test_a_duration_over_the_longest_raises(us):
    with pytest.raises(ValueError, match="too long"):
        pulses_to_data([328, us])
    with pytest.raises(ValueError, match="too long"):
        pulses_to_rm4_rf([328, -us], 433.92)
    with pytest.raises(ValueError, match="too long"):
        pulses_to_rm4_rf([328], 433.92, gap_us=us)


def test_one_pulse_frame_sent_once_needs_only_a_tail():
    packet = pulses_to_rm4_rf([328, -656, 328], 433.92, tail_us=984)
    assert packet[8:] == bytes([11, 22, 11, 32])
    with pytest.raises(ValueError, match="gap_us"):
        pulses_to_rm4_rf([328, -656, 328], 433.92, frames=2, tail_us=984)


def test_one_frame_ends_on_the_tail():
    packet = pulses_to_rm4_rf(ON, 433.92, gap_us=GAP, tail_us=TAIL)
    assert data_to_pulses(packet)[-1] == int(round(TAIL / TICK) * TICK)


@pytest.mark.parametrize("frames", [1, 4, 10])
def test_realign_leaves_a_built_packet_alone(frames):
    packet = pulses_to_rm4_rf(ON, 433.92, frames=frames, gap_us=GAP, tail_us=TAIL)
    assert realign_rf_packet(packet) == packet


@pytest.mark.parametrize("frames", [2.0, 2.5, "2"])
def test_refuses_frames_that_are_not_whole_numbers(frames):
    with pytest.raises(ValueError, match="frames"):
        pulses_to_rm4_rf([328, -656], 433.92, frames=frames)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_refuses_timings_that_are_not_finite(bad):
    with pytest.raises(ValueError, match="finite"):
        pulses_to_rm4_rf([328, -656, bad, -656], 433.92)
    with pytest.raises(ValueError, match="must be positive"):
        pulses_to_rm4_rf([328, -656], 433.92, gap_us=bad)
