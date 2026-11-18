"""Support for air purifiers."""

import enum

from . import exceptions as e
from .device import Device


class lifaair(Device):
    """Controls a Broadlink-based LIFAair air purifier / monitor.

    Product id 0x4EC2 is the LM05. The layout and the commands below were
    checked on firmware 10026 (pit3k/python-broadlink#1, continuing
    mjg59/python-broadlink#807).
    """

    TYPE = "LIFAAIR"

    @enum.unique
    class FanMode(enum.IntEnum):
        """Enumerates fan modes."""

        OFF = 0
        AUTO = 1
        NIGHT = 2
        TURBO = 3
        ANTI_ALLERGY = 4
        MANUAL = 5

        UNKNOWN = -1

    # Fan state byte (payload[55]). 0x01 is the purifier offline or unpaired.
    # On this unit (fw 10026) that is flags 0xC0 and temperature/humidity
    # bytes 00 00 00. Another LM05 instead kept raw 25 and 45 (decoded
    # 2.5 deg C / 45 %) with no purifier paired (mjg59/python-broadlink#807);
    # that is not special-cased. A restart or re-pair returns the purifier
    # itself to AUTO.
    _FAN_STATE_TO_MODE = {
        0x81: FanMode.OFF,
        0xA5: FanMode.AUTO,
        0x95: FanMode.NIGHT,
        0x8D: FanMode.TURBO,
        0x85: FanMode.MANUAL,
        0x01: None,  # main unit offline / unpaired
    }

    @enum.unique
    class _Operation(enum.IntEnum):
        SET_STATE = 1
        GET_STATE = 2

    @enum.unique
    class _Action(enum.IntEnum):
        SET_FAN_SPEED = 1
        SET_FAN_MODE = 2

    _FAN_MODE_TO_ACTION_ARG = {
        FanMode.OFF: 1,
        FanMode.AUTO: 2,
        FanMode.NIGHT: 6,
        FanMode.TURBO: 7,
        FanMode.ANTI_ALLERGY: 11,
    }

    async def set_fan_mode(self, fan_mode: FanMode) -> dict:
        """Set the fan mode. Returns the decoded response.

        In OFF only OFF and AUTO are accepted; NIGHT, TURBO and
        ANTI_ALLERGY raise the device error -5 (reported as StorageError)
        and nothing changes. AUTO from OFF reports speed 30 and may drop
        to 0 a few seconds later. NIGHT starts at 10, TURBO at 121,
        ANTI_ALLERGY at 60. There is no MANUAL command; use set_fan_speed().
        While the purifier main unit is offline the station rejects mode
        commands with the device error -5 (StorageError); the mode is not
        applied after the unit reconnects either.
        """
        action_arg = self._FAN_MODE_TO_ACTION_ARG.get(fan_mode)
        if action_arg is None:
            raise ValueError(f"{fan_mode!r} has no mode command")
        data = await self._send(
            self._Operation.SET_STATE, self._Action.SET_FAN_MODE, action_arg
        )
        return self._decode_state(data)

    async def set_fan_speed(self, fan_speed: int) -> dict:
        """Set fan speed (0-121). Returns the decoded response.

        Any mode except OFF reports MANUAL with the new speed (0 included).
        In OFF the speed is applied and the fan spins, but the device keeps
        reporting OFF. While the purifier main unit is offline the station
        answers with success but returns the offline state (purifier_online
        False) and the speed is not applied, neither then nor after the unit
        reconnects.
        """
        if not isinstance(fan_speed, int) or isinstance(fan_speed, bool):
            raise ValueError("fan_speed must be an int in 0..121")
        if not 0 <= fan_speed <= 121:
            raise ValueError("fan_speed must be an int in 0..121")
        data = await self._send(
            self._Operation.SET_STATE, self._Action.SET_FAN_SPEED, fan_speed
        )
        return self._decode_state(data)

    async def get_state(self) -> dict:
        """Return the current state of the purifier as a dict.

        CO2, TVOC, formaldehyde and PM come from the station. Temperature,
        humidity, fan mode and fan speed come from the purifier. They are
        None when it is offline (purifier_online is False); the speed byte
        is then 0, a placeholder. Temperature and humidity are also None
        when bytes 27-29 are placeholder zeros on the first poll after it
        reconnects. Fan mode and fan speed are otherwise the values the
        device reports, including AUTO at speed 0 and OFF with a non-zero
        speed.

        Format::

            {
                "temperature": 24.5,        # float, deg C, or None
                "humidity": 41,             # int, %, or None
                "co2": 425,                 # int, ppm
                "formaldehyde": 0.03,       # float, mg/m3
                "tvoc": 150,                # int, ug/m3
                "pm1": 5,                   # int, ug/m3
                "pm2_5": 7,                 # int, ug/m3
                "pm10": 9,                  # int, ug/m3
                "fan_mode": lifaair.FanMode.AUTO,  # lifaair.FanMode, or None
                "fan_speed": 50,            # int 0-121, or None
                "purifier_online": True,    # bool, bit 7 of byte 55
            }
        """
        data = await self._send(self._Operation.GET_STATE)
        return self._decode_state(data)

    def _decode_state(self, data: bytes) -> dict:
        raw = self._decode_state_raw(data)
        # Bit 7 of the fan-state byte is set whenever the purifier is online.
        purifier_online = bool(raw["fan_state"] & 0x80)
        fan_mode = self._decode_fan_mode(raw["fan_state"], raw["fan_flags"])
        # Bytes 27-29 are 00 00 00 when the purifier has no climate reading:
        # it is offline, or this is the first poll after it reconnects
        # (fan_state is already online). Not a real 0.0 deg C / 0 %.
        if not purifier_online or (raw["temperature"] == 0 and raw["humidity"] == 0):
            temperature = None
            humidity = None
        else:
            temperature = raw["temperature"] / 10.0
            humidity = raw["humidity"]
        # Mode and speed are reported independently: AUTO can report speed 0
        # (seen with clean air), and OFF reported speed 50 after set_fan_speed(50).
        # Offline frames carry speed 0 as a placeholder.
        return {
            "temperature": temperature,
            "humidity": humidity,
            "co2": raw["co2"],
            "formaldehyde": raw["formaldehyde"] / 100.0,
            "tvoc": raw["tvoc"] * 10,
            "pm1": raw["pm1"],
            "pm2_5": raw["pm2_5"],
            "pm10": raw["pm10"],
            "fan_mode": fan_mode,
            "fan_speed": raw["fan_speed"] if purifier_online else None,
            "purifier_online": purifier_online,
        }

    def _decode_state_raw(self, data: bytes) -> dict:
        # PM field order verified against LAM01/LM05 display (PM1 <= PM2.5 <= PM10).
        # Byte 30 is always 0x02. Meaning unknown; not decoded.
        # CO2 reads exactly 400 for up to ~10 s after the station starts (5/5)
        # and was also seen once when the main unit dropped out. 400 ppm can
        # be real, so it is kept.
        return {
            "temperature": data[27] + 256 * data[28],
            "humidity": data[29],
            "co2": data[31] + 256 * data[32],
            "formaldehyde": data[33] + 256 * data[34],
            "tvoc": data[35] + 256 * data[36],
            "pm1": data[37] + 256 * data[38],
            "pm2_5": data[39] + 256 * data[40],
            "pm10": data[41] + 256 * data[42],
            "fan_state": data[55],
            "fan_speed": data[56],
            "fan_flags": data[57],
        }

    def _decode_fan_mode(self, fan_state: int, fan_flags: int) -> FanMode | None:
        # Bit 7 clear: purifier offline or unpaired (observed as 0x01, flags 0xC0).
        if fan_state & 0x80 == 0:
            return None
        # Anti-allergy is 0x85 with bit 0x40 of the flags clear.
        if fan_flags & 0x40 == 0:
            return self.FanMode.ANTI_ALLERGY
        # Mode arguments 9 and 10 clear and set bit 0 of this byte without
        # changing mode or speed; meaning unknown.
        return self._FAN_STATE_TO_MODE.get(fan_state | 0x01, self.FanMode.UNKNOWN)

    async def _send(self, operation: int, action: int = 0, action_arg: int = 0) -> bytes:
        """Send a command to the device."""
        packet = bytearray(26)
        packet[0x02] = 0xA5
        packet[0x03] = 0xA5
        packet[0x04] = 0x5A
        packet[0x05] = 0x5A
        packet[0x08] = operation & 0xFF
        packet[0x0A] = 0x0C
        packet[0x0E] = action & 0xFF
        packet[0x0F] = action_arg & 0xFF

        checksum = sum(packet, 0xBEAF) & 0xFFFF
        packet[0x06] = checksum & 0xFF
        packet[0x07] = checksum >> 8

        packet_len = len(packet) - 2
        packet[0x00] = packet_len & 0xFF
        packet[0x01] = packet_len >> 8

        resp = await self.send_packet(0x6A, packet)
        # Seen returning -5 sporadically during power-cycling and pairing; cause unknown.
        e.check_error(resp[0x22:0x24])
        return self.decrypt(resp[0x38:])
