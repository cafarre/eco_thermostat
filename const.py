"""Provides the constants needed for component."""

from homeassistant.backports.enum import StrEnum


class HVACState(StrEnum):
    """HVAC state for climate devices."""

    AUTO = "auto"
    MANUAL = "manual"
    WINDOW_OPEN = "window-open"
    HOME_CLOSED = "home-closed"
    OFF = "off"


