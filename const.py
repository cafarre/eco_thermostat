"""Provides the constants needed for component."""
from enum import StrEnum

from homeassistant.components.climate import (
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
)

DOMAIN = "eco_thermostat"

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = "Eco Thermostat"

CONF_HEATER = "heater"
CONF_SENSOR = "target_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_AC_MODE = "ac_mode"
CONF_MIN_DUR = "min_cycle_duration"
CONF_MIN_CYCLE_DURATION = CONF_MIN_DUR
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_KEEP_ALIVE = "keep_alive"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_PRECISION = "precision"
CONF_TEMP_STEP = "target_temp_step"
CONF_TARGET_TEMP_STEP = CONF_TEMP_STEP

# Eco Thermostat specific fields
CONF_MIN_HOT_TOLERANCE = "min_hot_tolerance"
CONF_MAX_TEMP_JUMPS = "max_temp_jumps"
CONF_MAX_HEATING_LOCKED = "max_heating_locked"
CONF_MANUAL_TIMER = "manual_timer"
ATTR_HVAC_STATE = "hvac_state"
CONF_CALENDAR_HOLIDAYS = "calendar_holidays"
CONF_SCHEDULE_TEMP = "schedule_temp"
CONF_SCHEDULE_TEMP_HOLIDAY = "schedule_temp_holidays"
CONF_MAX_TIME_ON = "max_time_on"

CONF_PRESETS = {
    p: f"{p}_temp"
    for p in (
        PRESET_AWAY,
        PRESET_COMFORT,
        PRESET_HOME,
        PRESET_SLEEP,
        PRESET_ACTIVITY,
    )
}


class HVACState(StrEnum):
    """HVAC state for climate devices."""

    AUTO = "auto"
    MANUAL = "manual"
    WINDOW_OPEN = "window-open"
    HOME_CLOSED = "home-closed"
    OFF = "off"
