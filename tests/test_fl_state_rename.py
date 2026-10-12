"""Test state renaming for the Luceco Castra floodlight"""

from __future__ import annotations

from broadlink_async.light import fl
from tests.oracle.harness import HOST, MAC


def test_state_renaming():
    state = {"Brightness control": 5}
    dev = fl(HOST, MAC, 0x647A)
    new_state = dev._fix_state(state)
    assert "Brightness control" not in new_state
    assert "brightness_control" in new_state
    assert new_state["brightness_control"] == 5

    state = {"Delay time": 120}
    new_state = dev._fix_state(state)
    assert "Delay time" not in new_state
    assert "delay_time" in new_state
    assert new_state["delay_time"] == 120

    state = {"Brightness control": 5, "Delay time": 120}
    new_state = dev._fix_state(state)
    assert "Brightness control" not in new_state
    assert "brightness_control" in new_state
    assert new_state["brightness_control"] == 5
    assert "Delay time" not in new_state
    assert "delay_time" in new_state
    assert new_state["delay_time"] == 120
