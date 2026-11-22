"""Reading RM4 Pro RF captures on every carrier by their header.

An RM4 Pro writes a different first byte for each carrier it captures on,
so a capture is recognized by byte 1 (0xC0) and the carrier field at bytes
4 to 7, not by its first byte. The captures in the fixture are one per
carrier from a real device.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from broadlink_async.remote import (
    TICK,
    CapturedSignal,
    SignalKind,
    data_to_pulses,
    is_rm4_rf_packet,
    packet_kind,
    parse_packet,
    pulses_to_data,
    pulses_to_rm4_rf,
    realign_rf_packet,
    rf_carrier_mhz,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rm4pro_rf_carriers.json"
CAPTURES = {
    int(khz): bytes.fromhex(packet)
    for khz, packet in json.loads(FIXTURE.read_text())["captures"].items()
}
FIRST_BYTES = {
    305000: 0x64,
    315000: 0x78,
    320000: 0x82,
    335000: 0xA0,
    433420: 0xB0,
    433920: 0xB1,
    438000: 0xBA,
}


def old_reading(packet: bytes) -> list[int]:
    """The timings read from offset 4, as before this fix.

    Byte 1 is cleared so the header is not recognized.
    """
    return data_to_pulses(packet[:1] + b"\x00" + packet[2:])


def test_the_fixture_has_every_measured_carrier():
    assert {khz: packet[0] for khz, packet in CAPTURES.items()} == FIRST_BYTES


@pytest.mark.parametrize("khz", sorted(CAPTURES))
def test_capture_is_recognized_whatever_its_first_byte(khz):
    packet = CAPTURES[khz]
    assert is_rm4_rf_packet(packet)
    assert rf_carrier_mhz(packet) == khz / 1000


@pytest.mark.parametrize("khz", sorted(CAPTURES))
def test_capture_timings_start_after_the_carrier_field(khz):
    packet = CAPTURES[khz]
    pulses = data_to_pulses(packet)
    # The same timings an 0xB1 capture would give: the first byte is not
    # what decides where they start.
    assert pulses == data_to_pulses(bytes([0xB1]) + packet[1:])
    assert pulses[0] == int(packet[8] * TICK)
    if khz != 433920:
        # Read from offset 4, as before, the carrier field became four
        # timings in front and the first two real ones were lost.
        assert old_reading(packet)[4:] == pulses[2:]


@pytest.mark.parametrize("khz", sorted(CAPTURES))
def test_capture_kind_follows_its_carrier(khz):
    packet = CAPTURES[khz]
    expected = SignalKind.RF_315 if khz < 400_000 else SignalKind.RF_433
    assert packet_kind(packet) is expected
    parsed = parse_packet(packet)
    assert parsed.kind is expected
    assert parsed.type_byte == FIRST_BYTES[khz]
    assert parsed.frequency_mhz == khz / 1000
    assert parsed.pulses == tuple(data_to_pulses(packet))


@pytest.mark.parametrize("khz", sorted(CAPTURES))
def test_captured_signal_reads_its_own_carrier(khz):
    packet = CAPTURES[khz]
    signal = CapturedSignal.from_packet(packet, 999.0)
    assert signal.frequency_mhz == khz / 1000
    assert signal.type_byte == FIRST_BYTES[khz]
    assert signal.pulses == tuple(data_to_pulses(packet))


def test_315_capture_classifies_without_a_kind():
    # 0x78 is in no first-byte range, so this used to raise ValueError.
    with pytest.raises(ValueError, match="0x78"):
        SignalKind.classify(0x78)
    assert CapturedSignal.from_packet(CAPTURES[315000]).kind is SignalKind.RF_315


def test_realign_applies_on_any_carrier():
    # A capture at 315 MHz that started mid-pulse: its long gaps sit on
    # carrier-on slots. Realigning drops the stray first timing.
    aligned = bytes.fromhex("78c0150078ce04000d00019a280c0d280d00019a280c0d280d")
    misaligned = bytes.fromhex("78c0160078ce0400350d00019a280c0d280d00019a280c0d280d")
    assert realign_rf_packet(misaligned) == aligned
    assert realign_rf_packet(aligned) == aligned


def test_433_92_captures_read_as_before():
    packet = CAPTURES[433920]
    assert rf_carrier_mhz(packet) == 433.92
    assert parse_packet(packet).kind is SignalKind.RF_433


def test_built_rm4_packet_reads_back_on_other_carriers():
    for mhz in (305.0, 315.0, 433.42, 438.0):
        packet = pulses_to_rm4_rf([328, -656], mhz)
        assert is_rm4_rf_packet(packet)
        assert rf_carrier_mhz(packet) == mhz


@pytest.mark.parametrize("kind", [SignalKind.IR, SignalKind.RF_433, SignalKind.RF_315])
def test_four_byte_packets_are_not_rm4_rf(kind):
    packet = pulses_to_data([500, 1000, 500, 1000], kind=kind, repeat=3)
    assert not is_rm4_rf_packet(packet)
    assert rf_carrier_mhz(packet) is None
    assert parse_packet(packet).kind is kind


def test_four_byte_packet_with_repeat_192_is_not_mistaken():
    # Byte 1 of a 4-byte packet is a repeat count, and 192 is 0xC0. Its
    # first timings would have to read as a 300 to 950 MHz carrier to be
    # taken for an RM4 Pro header; ordinary timings do not.
    packet = pulses_to_data(
        [500, 1000, 500, 1000, 500], kind=SignalKind.RF_433, repeat=192
    )
    assert packet[1] == 0xC0
    assert not is_rm4_rf_packet(packet)
    assert parse_packet(packet).pulses[0] == int(round(500 / TICK) * TICK)


@pytest.mark.parametrize(
    "packet",
    [
        # Carrier field below 300 MHz.
        bytes.fromhex("78c00600f88f04000d0d"),
        # Carrier field above 950 MHz.
        bytes.fromhex("78c00600c0c62d000d0d"),
        # Length field shorter than the carrier field.
        bytes.fromhex("78c0020078ce04000d0d"),
        # Byte 1 is not 0xC0.
        bytes.fromhex("7800060078ce04000d0d"),
        # An IR code never has a carrier field.
        bytes.fromhex("26c0060078ce04000d0d"),
        # Too short to hold a carrier field.
        bytes.fromhex("78c0030078ce04"),
    ],
)
def test_headers_that_do_not_fit_are_not_rm4_rf(packet):
    assert not is_rm4_rf_packet(packet)
    assert rf_carrier_mhz(packet) is None
