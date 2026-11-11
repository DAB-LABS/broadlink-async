"""Data models for BroadLink Magic families and gateways."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .const import (
    AC_DEVTYPE,
    AC_PID,
    RM_MAX_PID,
    STB_DEVTYPE,
    STB_PID,
    SWITCH_PROTOCOL_DEVTYPES,
    THREE_IN_ONE_PID,
    TV_DEVTYPE,
    TV_PID,
)


class RMProfile(StrEnum):
    """Known RM Max child-device profiles."""

    TV = "tv"
    STB = "stb"
    PROJECTOR = "projector"
    SMART_BOX = "smart_box"
    DVD = "dvd"
    SPEAKER = "speaker"
    AMPLIFIER = "amplifier"
    AC = "ac"
    CURTAIN = "curtain"
    FAN = "fan"
    RM_LIGHT = "rm_light"
    PURIFIER = "purifier"
    WATER_HEATER = "water_heater"
    HUMIDIFIER = "humidifier"
    VACUUM = "vacuum"
    DRYING_RACK = "drying_rack"
    RELAY_PANEL = "relay_panel"
    LEARNED_IR = "learned_ir"
    LEARNED_RF = "learned_rf"


RM_PROFILE_BY_PID: dict[str, RMProfile] = {
    "2baf": RMProfile.TV,
    "2caf": RMProfile.STB,
    "2daf": RMProfile.PROJECTOR,
    "59b2": RMProfile.SMART_BOX,
    "2faf": RMProfile.DVD,
    "5cb2": RMProfile.SPEAKER,
    "5db2": RMProfile.AMPLIFIER,
    "8fab": RMProfile.AC,
    "61b0": RMProfile.CURTAIN,
    "2ab2": RMProfile.CURTAIN,
    "2eaf": RMProfile.FAN,
    "60b0": RMProfile.RM_LIGHT,
    "2aa8": RMProfile.RM_LIGHT,
    "5eb2": RMProfile.PURIFIER,
    "5fb2": RMProfile.WATER_HEATER,
    "62b2": RMProfile.HUMIDIFIER,
    "63b2": RMProfile.VACUUM,
    "65b2": RMProfile.DRYING_RACK,
    "5ab1": RMProfile.RELAY_PANEL,
    "32af": RMProfile.LEARNED_IR,
    "deb1": RMProfile.LEARNED_RF,
}


def normalize_pid(value: str | None) -> str:
    """Normalize a PID to a lower-case 32-character string."""
    if not value:
        return ""
    return value.strip().lower().zfill(32)


def rm_profile_for_pid(value: str | None) -> RMProfile | None:
    """Return the RM profile represented by a full or short PID."""
    pid = normalize_pid(value)
    suffix = pid[-8:-4] if pid.endswith("0000") else pid[-4:]
    return RM_PROFILE_BY_PID.get(suffix)


def normalize_mac(value: str | None) -> str:
    """Normalize a MAC or BroadLink DID to twelve lower-case hex characters."""
    if not value:
        return ""
    compact = value.lower().replace(":", "").replace("-", "").strip()
    if "_" in compact:
        compact = compact.split("_", 1)[0]
    return compact[-12:] if len(compact) >= 12 else compact


class DeviceKind(StrEnum):
    """Imported device kind."""

    GATEWAY = "gateway"
    GROUP = "group"
    AC = "ac"
    TV = "tv"
    STB = "stb"
    RM_REMOTE = "rm_remote"
    RM_CURTAIN = "rm_curtain"
    RM_FAN = "rm_fan"
    RM_LIGHT = "rm_light"
    RM_POWER = "rm_power"
    RM_VACUUM = "rm_vacuum"
    RM_DRYING_RACK = "rm_drying_rack"
    RM_RELAY = "rm_relay"
    LIGHT = "light"
    SWITCH = "switch"
    PLUG = "plug"
    CURTAIN = "curtain"
    OTHER = "other"


@dataclass(slots=True, frozen=True)
class Room:
    """A room imported from Magic Home."""

    room_id: int
    name: str


@dataclass(slots=True, frozen=True)
class VirtualSubToken:
    """A virtual subdevice token."""

    did: str
    pid: str
    token: str
    type: str = ""


@dataclass(slots=True)
class ImportedDevice:
    """A device imported from the family devlist."""

    did: str
    pid: str
    name: str
    mac: str = ""
    sdid: str = ""
    spid: str = ""
    short_addr: int | None = None
    ble_category: str = ""
    ble_device_type: str = ""
    devtype: int | None = None
    room_id: int | None = None
    token: str = ""
    bletoken: str = ""
    version: str = ""
    channel_count: int = 1
    channel_names: list[str] = field(default_factory=list)
    is_rm_child: bool = False
    rm_profile: RMProfile | None = None
    functions: dict[str, int] = field(default_factory=dict)
    raw: dict[str, object] = field(default_factory=dict, repr=False)

    @property
    def effective_pid(self) -> str:
        """Return the subdevice PID when available."""
        return normalize_pid(self.spid or self.pid)

    @property
    def is_three_in_one(self) -> bool:
        """Return whether this is an AC, floor-heating and fresh-air panel."""
        return not self.is_rm_child and self.effective_pid == THREE_IN_ONE_PID

    @property
    def stable_id(self) -> str:
        """Return a stable imported device identifier."""
        return self.sdid or self.did or self.mac

    @property
    def kind(self) -> DeviceKind:
        """Classify this imported device."""
        pid = self.effective_pid
        category = self.ble_category.upper()
        if self.ble_device_type.upper() == "GROUP":
            return DeviceKind.GROUP
        if (normalize_pid(self.pid) == RM_MAX_PID and not self.sdid) or (
            self.ble_device_type.upper() == "BLEGATEWAY"
            and normalize_pid(self.pid) == RM_MAX_PID
        ):
            return DeviceKind.GATEWAY
        if self.is_rm_child and self.rm_profile is not None:
            if self.rm_profile is RMProfile.TV:
                return DeviceKind.TV
            if self.rm_profile is RMProfile.STB:
                return DeviceKind.STB
            if self.rm_profile is RMProfile.AC:
                return DeviceKind.AC
            if self.rm_profile in {
                RMProfile.PROJECTOR,
                RMProfile.SMART_BOX,
                RMProfile.DVD,
                RMProfile.SPEAKER,
                RMProfile.AMPLIFIER,
            }:
                return DeviceKind.RM_REMOTE
            if self.rm_profile is RMProfile.CURTAIN:
                return DeviceKind.RM_CURTAIN
            if self.rm_profile is RMProfile.FAN:
                return DeviceKind.RM_FAN
            if self.rm_profile is RMProfile.RM_LIGHT:
                return DeviceKind.RM_LIGHT
            if self.rm_profile in {
                RMProfile.PURIFIER,
                RMProfile.WATER_HEATER,
                RMProfile.HUMIDIFIER,
            }:
                return DeviceKind.RM_POWER
            if self.rm_profile is RMProfile.VACUUM:
                return DeviceKind.RM_VACUUM
            if self.rm_profile is RMProfile.DRYING_RACK:
                return DeviceKind.RM_DRYING_RACK
            if self.rm_profile is RMProfile.RELAY_PANEL:
                return DeviceKind.RM_RELAY
            return DeviceKind.OTHER
        if self.is_rm_child:
            return DeviceKind.OTHER
        if pid == TV_PID or self.devtype == TV_DEVTYPE or category == "TV":
            return DeviceKind.TV
        if pid == STB_PID or self.devtype == STB_DEVTYPE or category == "STB":
            return DeviceKind.STB
        if pid == AC_PID or self.devtype == AC_DEVTYPE or category == "BLEAC":
            return DeviceKind.AC
        if category == "CURTAIN":
            return DeviceKind.CURTAIN
        if category == "PLUG":
            return DeviceKind.PLUG
        if category == "SWITCH" or self.devtype in SWITCH_PROTOCOL_DEVTYPES:
            return DeviceKind.SWITCH
        if "LIGHT" in category:
            return DeviceKind.LIGHT
        return DeviceKind.OTHER


@dataclass(slots=True)
class ImportedGroup:
    """A device group imported from Magic Home."""

    group_id: int
    name: str
    ble_category: str = ""
    room_id: int | None = None
    room_name: str = ""
    member_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportedScene:
    """A scene imported from Magic Home."""

    scene_id: str
    name: str
    room_id: int | None = None
    room_name: str = ""
    module_devices: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class Family:
    """A Magic Home family snapshot."""

    family_id: str
    name: str
    bletoken: str
    pid: str = ""
    token: str = ""
    rooms: list[Room] = field(default_factory=list)
    devices: list[ImportedDevice] = field(default_factory=list)
    groups: list[ImportedGroup] = field(default_factory=list)
    scenes: list[ImportedScene] = field(default_factory=list)
    virtual_subtokens: list[VirtualSubToken] = field(default_factory=list)

    @property
    def gateways(self) -> list[ImportedDevice]:
        """Return RM Max gateways in this family."""
        return [device for device in self.devices if device.kind is DeviceKind.GATEWAY]

    @property
    def remote_devices(self) -> list[ImportedDevice]:
        """Return TV and STB devices in this family."""
        return [
            device
            for device in self.devices
            if device.kind in {DeviceKind.TV, DeviceKind.STB}
        ]

    @property
    def rm_remote_devices(self) -> list[ImportedDevice]:
        """Return supported RM audio/video remote devices."""
        return [
            device
            for device in self.devices
            if device.is_rm_child
            and device.kind in {DeviceKind.TV, DeviceKind.STB, DeviceKind.RM_REMOTE}
        ]

    @property
    def rm_companion_devices(self) -> list[ImportedDevice]:
        """Return supported non-AV RM child devices."""
        supported = {
            DeviceKind.RM_CURTAIN,
            DeviceKind.RM_FAN,
            DeviceKind.RM_LIGHT,
            DeviceKind.RM_POWER,
            DeviceKind.RM_VACUUM,
            DeviceKind.RM_DRYING_RACK,
            DeviceKind.RM_RELAY,
        }
        return [device for device in self.devices if device.kind in supported]

    @property
    def rm_curtain_devices(self) -> list[ImportedDevice]:
        """Return RM curtain devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_CURTAIN]

    @property
    def rm_fan_devices(self) -> list[ImportedDevice]:
        """Return RM fan devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_FAN]

    @property
    def rm_light_devices(self) -> list[ImportedDevice]:
        """Return RM light devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_LIGHT]

    @property
    def rm_power_devices(self) -> list[ImportedDevice]:
        """Return RM purifier, water-heater, and humidifier devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_POWER]

    @property
    def rm_vacuum_devices(self) -> list[ImportedDevice]:
        """Return RM vacuum devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_VACUUM]

    @property
    def rm_drying_rack_devices(self) -> list[ImportedDevice]:
        """Return RM drying-rack devices."""
        return [
            device for device in self.devices if device.kind is DeviceKind.RM_DRYING_RACK
        ]

    @property
    def rm_relay_devices(self) -> list[ImportedDevice]:
        """Return RM relay-panel devices."""
        return [device for device in self.devices if device.kind is DeviceKind.RM_RELAY]

    @property
    def rm_learned_devices(self) -> list[ImportedDevice]:
        """Return RM learned IR and RF devices."""
        return [
            device
            for device in self.devices
            if device.is_rm_child
            and device.rm_profile in {RMProfile.LEARNED_IR, RMProfile.LEARNED_RF}
        ]

    @property
    def climate_devices(self) -> list[ImportedDevice]:
        """Return imported RM Max air conditioners."""
        return [device for device in self.devices if device.kind is DeviceKind.AC]

    @property
    def three_in_one_devices(self) -> list[ImportedDevice]:
        """Return AC, floor-heating and fresh-air thermostat panels."""
        return [
            device
            for device in self.devices
            if device.kind is DeviceKind.AC and device.is_three_in_one
        ]

    @property
    def light_devices(self) -> list[ImportedDevice]:
        """Return imported Bluetooth lights."""
        return [device for device in self.devices if device.kind is DeviceKind.LIGHT]

    @property
    def switch_devices(self) -> list[ImportedDevice]:
        """Return imported switch panels and plugs."""
        return [
            device
            for device in self.devices
            if device.kind in {DeviceKind.SWITCH, DeviceKind.PLUG}
        ]

    @property
    def curtain_devices(self) -> list[ImportedDevice]:
        """Return imported curtain motors."""
        return [device for device in self.devices if device.kind is DeviceKind.CURTAIN]

    @property
    def light_groups(self) -> list[ImportedGroup]:
        """Return imported light groups."""
        return [group for group in self.groups if "LIGHT" in group.ble_category.upper()]

    def gateway_token(self, mac: str) -> str:
        """Return the imported LAN AES token for a gateway."""
        normalized = normalize_mac(mac)
        for device in self.gateways:
            if normalize_mac(device.mac or device.did) == normalized and device.token:
                return device.token
        for virtual_token in self.virtual_subtokens:
            if normalize_mac(virtual_token.did) == normalized and virtual_token.token:
                return virtual_token.token
        return self.token


@dataclass(slots=True, frozen=True)
class DiscoveredRMMax:
    """An RM Max discovered on the local network."""

    host: str
    mac: str
    devtype: int
    name: str = ""
    locked: bool = False
    port: int = 80
