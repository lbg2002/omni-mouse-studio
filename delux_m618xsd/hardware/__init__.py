"""Hardware communication layer for Delux M618XSD (/dev/hidraw)."""

from .hidraw import HidrawDevice, HidrawError, HidrawNode, enumerate_hidraw
from .protocol import (
    BatteryEvent,
    ButtonSettings,
    ButtonSlot,
    DpiCycleEvent,
    DpiSettings,
    FIRMWARE_ACTIONS,
    LIGHT_MODES,
    LightingSettings,
    M618XSD_SLOTS,
    POLL_RATES,
    PollingRate,
    ProfileChangedEvent,
    ProfileSettings,
)
from .session import M618XSDSession, SessionError, find_m618xsd_node, list_m618xsd_nodes

__all__ = [
    "BatteryEvent",
    "ButtonSettings",
    "ButtonSlot",
    "DpiCycleEvent",
    "DpiSettings",
    "FIRMWARE_ACTIONS",
    "HidrawDevice",
    "HidrawError",
    "HidrawNode",
    "LIGHT_MODES",
    "LightingSettings",
    "M618XSDSession",
    "M618XSD_SLOTS",
    "POLL_RATES",
    "PollingRate",
    "ProfileChangedEvent",
    "ProfileSettings",
    "SessionError",
    "enumerate_hidraw",
    "find_m618xsd_node",
    "list_m618xsd_nodes",
]
