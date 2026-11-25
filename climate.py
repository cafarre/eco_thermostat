"""Adds support for eco thermostat units."""
from __future__ import annotations

import asyncio
from datetime import datetime, time as time_sys, timedelta
import logging
import math
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    PLATFORM_SCHEMA,
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_NONE,
    PRESET_SLEEP,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
try:
    from homeassistant.components.timer import STATUS_ACTIVE, STATUS_IDLE
except ImportError:
    STATUS_ACTIVE = "active"
    STATUS_IDLE = "idle"
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, CoreState, HomeAssistant, callback
from homeassistant.exceptions import ConditionError
from homeassistant.helpers import condition, entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt_util

from . import DOMAIN, PLATFORMS
from .const import (
    ATTR_HVAC_STATE,
    ATTR_HVAC_STATE_PREVIOUS,
    CONF_WINDOW_SENSOR,
    DEFAULT_DOOR_OPEN_DELAY_SECONDS,
    DEFAULT_WINDOW_OPEN_DELAY_SECONDS,
    HVACState,
    VALID_PREVIOUS_HVAC_STATES,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = "Eco Thermostat"

CONF_HEATER = "heater"
CONF_SENSOR = "target_sensor"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_AC_MODE = "ac_mode"
CONF_MIN_DUR = "min_cycle_duration"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_KEEP_ALIVE = "keep_alive"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_PRECISION = "precision"
CONF_TEMP_STEP = "target_temp_step"

# New fields
CONF_MIN_HOT_TOLERANCE = "min_hot_tolerance"
CONF_MAX_TEMP_JUMPS = "max_temp_jumps"
CONF_MAX_HEATING_LOCKED = "max_heating_locked"
CONF_MANUAL_TIMER = "manual_timer"
CONF_WINDOW_SENSOR = "window_sensor"
ATTR_HVAC_STATE = "hvac_state"
ATTR_HVAC_STATE_PREVIOUS = "hvac_state_previous"
ATTR_DURATION = "duration"
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


def time_validation(value: Any) -> time_sys:
    """Time valiadtion."""
    time = cv.time(value)
    return time


def _format_timedelta(delta: timedelta):
    total_seconds = delta.total_seconds()
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours)}:{int(minutes):02}:{int(seconds):02}"


SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("start"): time_validation,
        vol.Required("end"): time_validation,
        vol.Required("temp"): vol.Coerce(float),
    }
)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HEATER): cv.entity_id,
        vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Optional(CONF_AC_MODE): cv.boolean,
        vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_DUR): cv.positive_time_period,
        vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(CONF_KEEP_ALIVE): cv.positive_time_period,
        vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
            [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
        ),
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(CONF_TEMP_STEP): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        # New fields
        vol.Optional(CONF_MIN_HOT_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(
            float
        ),
        vol.Optional(CONF_MAX_TEMP_JUMPS, default=[]): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("delta"): vol.Coerce(float),
                        vol.Required("tolerance"): vol.Coerce(float),
                    }
                )
            ],
        ),
        vol.Optional(CONF_MAX_HEATING_LOCKED): cv.positive_time_period,
        vol.Optional(CONF_MANUAL_TIMER): cv.entity_id,
        vol.Optional(CONF_CALENDAR_HOLIDAYS): cv.entity_id,
        vol.Optional(CONF_SCHEDULE_TEMP, default=[]): vol.All(
            cv.ensure_list, [SCHEDULE_SCHEMA]
        ),
        vol.Optional(CONF_SCHEDULE_TEMP_HOLIDAY, default=[]): vol.All(
            cv.ensure_list, [SCHEDULE_SCHEMA]
        ),
        vol.Optional(CONF_MAX_TIME_ON): cv.positive_time_period,
    }
).extend({vol.Optional(v): vol.Coerce(float) for (k, v) in CONF_PRESETS.items()})


def _parse_duration(val: Any) -> timedelta | None:
    """Parse duration from dict, string, or timedelta."""
    if val is None:
        return None
    if isinstance(val, timedelta):
        return val
    try:
        return cv.time_period(val)
    except Exception:
        _LOGGER.warning("Could not parse time period: %s", val)
        return None


_SERVICES_REGISTERED = "eco_thermostat_services_registered"


@callback
def _async_register_services(hass: HomeAssistant, platform: entity_platform.EntityPlatform) -> None:
    """Register platform entity services once."""
    if hass.data.get(_SERVICES_REGISTERED):
        return

    platform.async_register_entity_service(
        "set_hvac_state",
        {
            vol.Required(ATTR_HVAC_STATE): vol.Coerce(HVACState),
        },
        "async_set_hvac_state",
    )
    platform.async_register_entity_service(
        "set_timer_duration",
        {
            vol.Required(ATTR_DURATION): cv.time_period,
        },
        "async_set_timer_duration",
    )
    hass.data[_SERVICES_REGISTERED] = True


def create_eco_thermostat(
    hass: HomeAssistant,
    config: dict[str, Any],
    unique_id: str | None = None,
) -> EcoThermostat:
    """Create an EcoThermostat instance from a configuration dictionary."""
    name = config.get(CONF_NAME, DEFAULT_NAME)
    heater_entity_id = config.get(CONF_HEATER)
    sensor_entity_id = config.get(CONF_SENSOR)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    ac_mode = config.get(CONF_AC_MODE, False)
    min_cycle_duration = _parse_duration(config.get(CONF_MIN_DUR))
    cold_tolerance = config.get(CONF_COLD_TOLERANCE, DEFAULT_TOLERANCE)
    hot_tolerance = config.get(CONF_HOT_TOLERANCE, DEFAULT_TOLERANCE)
    keep_alive = _parse_duration(config.get(CONF_KEEP_ALIVE))
    initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
    presets = {
        key: float(config[value])
        for key, value in CONF_PRESETS.items()
        if value in config and config[value] is not None
    }
    precision = (
        float(config[CONF_PRECISION])
        if config.get(CONF_PRECISION) is not None
        else None
    )
    target_temperature_step = (
        float(config[CONF_TEMP_STEP])
        if config.get(CONF_TEMP_STEP) is not None
        else None
    )
    unit = hass.config.units.temperature_unit
    unique_id = unique_id or config.get(CONF_UNIQUE_ID)

    min_hot_tolerance = config.get(CONF_MIN_HOT_TOLERANCE, DEFAULT_TOLERANCE)
    max_temp_jumps = config.get(CONF_MAX_TEMP_JUMPS) or []
    max_heating_locked = _parse_duration(config.get(CONF_MAX_HEATING_LOCKED))
    manual_timer = config.get(CONF_MANUAL_TIMER)
    calendar_holidays = config.get(CONF_CALENDAR_HOLIDAYS)
    schedule_temp = config.get(CONF_SCHEDULE_TEMP) or []
    schedule_temp_holidays = config.get(CONF_SCHEDULE_TEMP_HOLIDAY) or []
    max_time_on = _parse_duration(config.get(CONF_MAX_TIME_ON))
    window_sensor = config.get(CONF_WINDOW_SENSOR)

    return EcoThermostat(
        name,
        heater_entity_id,
        sensor_entity_id,
        min_temp,
        max_temp,
        target_temp,
        ac_mode,
        min_cycle_duration,
        cold_tolerance,
        hot_tolerance,
        keep_alive,
        initial_hvac_mode,
        presets,
        precision,
        target_temperature_step,
        unit,
        unique_id,
        min_hot_tolerance,
        max_temp_jumps,
        max_heating_locked,
        manual_timer,
        calendar_holidays,
        schedule_temp,
        schedule_temp_holidays,
        max_time_on,
        window_sensor,
    )


_create_eco_thermostat = create_eco_thermostat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eco Thermostat from a config entry."""
    platform = entity_platform.async_get_current_platform()
    _async_register_services(hass, platform)

    thermostat = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if thermostat is None:
        config = {**entry.data, **entry.options}
        unique_id = entry.unique_id or entry.entry_id
        thermostat = create_eco_thermostat(hass, config, unique_id=unique_id)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = thermostat

    async_add_entities([thermostat])


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the eco thermostat platform from YAML."""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    unique_id = config.get(CONF_UNIQUE_ID)
    if not unique_id:
        unique_id = f"eco_{config[CONF_HEATER]}_{config[CONF_SENSOR]}"

    # Check if a config entry already exists for this unique_id
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    if any(entry.unique_id == unique_id for entry in existing_entries):
        _LOGGER.debug(
            "Eco Thermostat entity '%s' (unique_id: %s) is already configured via UI. Skipping YAML setup.",
            config.get(CONF_NAME),
            unique_id,
        )
        return

    _LOGGER.warning(
        "Configuring Eco Thermostat via YAML is deprecated and will be removed in a future version. "
        "Your configuration for '%s' (unique_id: %s) has been automatically imported into Home Assistant "
        "(Settings -> Devices & Services). You can safely remove it from your YAML configuration files.",
        config.get(CONF_NAME, DEFAULT_NAME),
        unique_id,
    )

    import_data = dict(config)
    import_data[CONF_UNIQUE_ID] = unique_id

    import_success = False
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=import_data,
        )
        if result and result.get("type") == "create_entry":
            import_success = True
    except Exception as err:
        _LOGGER.debug("YAML import failed for %s: %s", unique_id, err)

    # If import didn't immediately create an active entry, ensure entity is loaded directly from YAML
    if not import_success:
        platform = entity_platform.async_get_current_platform()
        _async_register_services(hass, platform)
        thermostat = _create_eco_thermostat(hass, config, unique_id=unique_id)
        async_add_entities([thermostat])


class EcoThermostat(ClimateEntity, RestoreEntity):
    """Representation of a Eco Thermostat device."""

    _attr_should_poll = False

    def __init__(
        self,
        name,
        heater_entity_id,
        sensor_entity_id,
        min_temp,
        max_temp,
        target_temp,
        ac_mode,
        min_cycle_duration,
        cold_tolerance,
        hot_tolerance,
        keep_alive,
        initial_hvac_mode,
        presets,
        precision,
        target_temperature_step,
        unit,
        unique_id,
        min_hot_tolerance,
        max_temp_jumps,
        max_heating_locked,
        manual_timer,
        calendar_holidays,
        schedule_temp,
        schedule_temp_holidays,
        max_time_on,
        window_sensor=None,
    ) -> None:
        """Initialize the thermostat."""
        self._attr_name = name
        self.heater_entity_id = heater_entity_id
        self.sensor_entity_id = sensor_entity_id
        self.ac_mode = ac_mode
        self.min_cycle_duration = min_cycle_duration
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance
        self._keep_alive = keep_alive
        self._hvac_mode = initial_hvac_mode
        self._saved_target_temp = target_temp or next(iter(presets.values()), None)
        self._temp_precision = precision
        self._temp_target_temperature_step = target_temperature_step
        if self.ac_mode:
            self._attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
        else:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._active = False
        self._cur_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._attr_preset_mode = PRESET_NONE
        self._target_temp = target_temp
        self._attr_native_temperature_unit = unit
        self._attr_temperature_unit = unit
        self._attr_unique_id = unique_id

        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if len(presets):
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE, *presets.keys()]
        else:
            self._attr_preset_modes = [PRESET_NONE]
        self._presets = presets

        # New fields
        self._min_hot_tolerance = min_hot_tolerance
        self._max_temp_jumps = max_temp_jumps
        self._heating_locked_since = None
        self._max_heating_locked = max_heating_locked
        self._hvac_state = HVACState.AUTO
        self._hvac_state_previous = HVACState.AUTO
        self._window_sensor = window_sensor
        self._child_window_sensors: list[str] = []
        self._pending_open_timers: dict[str, Callable[[], None]] = {}
        self._unsub_waiting_temp = None
        self._timer_duration = None
        self._manual_duration_minutes = 30
        self._manual_timer_end: datetime | None = None
        self._manual_remaining_seconds: float = 0.0
        self._unsub_manual_timer = None
        self._timer_update_callbacks: list[Callable[[], None]] = []
        self._hvac_state_before = None
        self._hvac_mode_before = None
        self._manual_timer = manual_timer
        self._target_temp_before = None
        self._calendar_holidays = calendar_holidays
        self._schedule_temp = schedule_temp
        self._schedule_temp_holidays = schedule_temp_holidays
        self._max_time_on = max_time_on

        # New Attr
        self._attr_is_holiday = False
        self._attr_is_week_holiday = False
        self._attr_is_calendar_holiday = False
        self._attr_next_temperature = None
        self._attr_next_temperature_time = None
        self._attr_poweron_since = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.heater_entity_id], self._async_switch_changed
            )
        )

        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_control_heating, self._keep_alive
                )
            )

        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_control_heating_lock, timedelta(seconds=5)
            )
        )

        if self._manual_timer:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._manual_timer], self._async_timer_changed
                )
            )

        if self._calendar_holidays:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_every_minute_event, timedelta(seconds=60)
                )
            )

        if self._window_sensor:
            self._child_window_sensors = self._get_associated_window_entities()
            all_sensors = list(dict.fromkeys([self._window_sensor, *self._child_window_sensors]))
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, all_sensors, self._async_window_sensor_changed
                )
            )

        @callback
        def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
                self.async_write_ha_state()

            switch_state = self.hass.states.get(self.heater_entity_id)
            if switch_state and switch_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self.hass.create_task(self._check_switch_initial_state())

            if self._window_sensor:
                new_children = self._get_associated_window_entities()
                if new_children and new_children != self._child_window_sensors:
                    self._child_window_sensors = new_children
                    self.async_on_remove(
                        async_track_state_change_event(
                            self.hass, self._child_window_sensors, self._async_window_sensor_changed
                        )
                    )
                self.hass.create_task(self._check_window_initial_state())

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        if (old_state := await self.async_get_last_state()) is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self.ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if (
                self.preset_modes
                and old_state.attributes.get(ATTR_PRESET_MODE) in self.preset_modes
            ):
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)

            if not self._hvac_mode and old_state.state:
                if old_state.state in self.hvac_modes:
                    self._hvac_mode = HVACMode(old_state.state)
                elif old_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    try:
                        self._hvac_mode = HVACMode(old_state.state)
                    except ValueError:
                        self._hvac_mode = HVACMode.OFF

            if (restored_state := old_state.attributes.get(ATTR_HVAC_STATE)) is not None:
                try:
                    self._hvac_state = HVACState(restored_state)
                except ValueError:
                    self._hvac_state = HVACState.AUTO

            if (restored_prev := old_state.attributes.get(ATTR_HVAC_STATE_PREVIOUS)) is not None:
                try:
                    prev_val = HVACState(restored_prev)
                    if prev_val in VALID_PREVIOUS_HVAC_STATES:
                        self._hvac_state_previous = prev_val
                    else:
                        self._hvac_state_previous = HVACState.AUTO
                except ValueError:
                    self._hvac_state_previous = HVACState.AUTO
            else:
                if self._hvac_state in VALID_PREVIOUS_HVAC_STATES:
                    self._hvac_state_previous = self._hvac_state
                else:
                    self._hvac_state_previous = HVACState.AUTO

            if (finishes_at := old_state.attributes.get("timer_finishes_at")) is not None:
                try:
                    self._manual_timer_end = dt_util.parse_datetime(finishes_at)
                    now = dt_util.utcnow()
                    if self._manual_timer_end is not None and now >= self._manual_timer_end:
                        self._manual_timer_end = None
                        self._manual_remaining_seconds = 0.0
                        if self._hvac_state == HVACState.MANUAL:
                            self._hvac_state = HVACState.AUTO
                        if self._hvac_state_previous == HVACState.MANUAL:
                            self._hvac_state_previous = HVACState.AUTO
                    elif self._manual_timer_end is not None:
                        if (
                            self._hvac_state == HVACState.MANUAL
                            or self._hvac_state_previous == HVACState.MANUAL
                        ):
                            remaining = (self._manual_timer_end - now).total_seconds()
                            self._manual_remaining_seconds = max(0.0, remaining)
                            self._schedule_internal_timer(self._manual_remaining_seconds)
                        else:
                            self._manual_timer_end = None
                            self._manual_remaining_seconds = 0.0
                except Exception:
                    self._manual_timer_end = None
                    self._manual_remaining_seconds = 0.0

            # Avoid staying stuck in MANUAL with no active timer deadline
            if self._hvac_state == HVACState.MANUAL and self._manual_timer_end is None:
                self._hvac_state = HVACState.AUTO
                if self._hvac_state_previous == HVACState.MANUAL:
                    self._hvac_state_previous = HVACState.AUTO

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self.ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default mode based on HVAC state
        if self._hvac_state in (HVACState.AUTO, HVACState.MANUAL):
            self._hvac_mode = HVACMode.COOL if self.ac_mode else HVACMode.HEAT
        else:
            self._hvac_mode = HVACMode.OFF

        self._heating_locked_since = None
        await self._async_control_schedules()
        await self._async_control_heating()
        self._init_timer_duration()

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        if self._temp_target_temperature_step is not None:
            return self._temp_target_temperature_step
        # if a target_temperature_step is not defined, fallback to equal the precision
        return self.precision

    @property
    def native_current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def current_temperature(self):
        """Return the sensor temperature (backward compatibility)."""
        return self.native_current_temperature

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_state(self):
        """Return current state."""
        return self._hvac_state

    @property
    def hvac_state_previous(self):
        """Return previous HVAC state."""
        return self._hvac_state_previous

    @property
    def window_sensor(self):
        """Return window binary_sensor entity id."""
        return self._window_sensor

    @property
    def timer_duration(self):
        """Return current timer duration."""
        return self._timer_duration

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self._is_device_active:
            return HVACAction.IDLE
        if self.ac_mode:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def native_target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach (backward compatibility)."""
        return self.native_target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode in (HVACMode.HEAT, HVACMode.COOL):
            if self._hvac_state not in (HVACState.AUTO, HVACState.MANUAL):
                _LOGGER.warning(
                    "Cannot set HVAC mode to %s while HVAC state is %s",
                    hvac_mode,
                    self._hvac_state,
                )
                self.async_write_ha_state()
                return

        if hvac_mode == HVACMode.HEAT:
            self._hvac_mode = HVACMode.HEAT
            self._heating_locked_since = None
            await self._async_control_heating(force=True)
            self._hvac_mode_before = None
        elif hvac_mode == HVACMode.COOL:
            self._hvac_mode = HVACMode.COOL
            await self._async_control_heating(force=True)
            self._hvac_mode_before = None
        elif hvac_mode == HVACMode.OFF:
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
            self._hvac_mode_before = None
            if self._hvac_state in (HVACState.AUTO, HVACState.MANUAL):
                await self.async_set_hvac_state(HVACState.OFF)
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    @property
    def manual_duration_minutes(self) -> int:
        """Return manual duration in minutes."""
        return self._manual_duration_minutes

    @property
    def manual_timer_end(self) -> datetime | None:
        """Return manual timer end datetime."""
        return self._manual_timer_end

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id or self.name)},
            name=self._attr_name,
            manufacturer="Eco Thermostat",
            model="Virtual Thermostat",
        )

    def register_timer_update_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register callback for timer/duration updates."""
        self._timer_update_callbacks.append(callback)
        def _unregister():
            if callback in self._timer_update_callbacks:
                self._timer_update_callbacks.remove(callback)
        return _unregister

    def _async_notify_listeners(self) -> None:
        """Notify listeners of timer updates."""
        for cb in self._timer_update_callbacks:
            try:
                cb()
            except Exception as err:
                _LOGGER.error("Error in timer update callback: %s", err)

    def _cancel_internal_timer(self) -> None:
        """Cancel active internal timer callback."""
        if self._unsub_manual_timer is not None:
            self._unsub_manual_timer()
            self._unsub_manual_timer = None

    def _schedule_internal_timer(self, remaining_seconds: float) -> None:
        """Schedule internal manual timer expiration callback."""
        self._cancel_internal_timer()

        @callback
        def _timer_expired(_=None):
            self._unsub_manual_timer = None
            self._manual_timer_end = None
            self._manual_remaining_seconds = 0.0
            _LOGGER.info(
                "EcoThermostat %s manual timer expired. Returning to AUTO",
                self.entity_id or self.name,
            )
            if self._hvac_state in (HVACState.WINDOW_OPEN, HVACState.WAITING_TEMP):
                self._hvac_state_previous = HVACState.AUTO
                self._async_notify_listeners()
                self.async_write_ha_state()
            else:
                self.hass.create_task(self.async_set_hvac_state(HVACState.AUTO))

        self._unsub_manual_timer = async_call_later(
            self.hass,
            max(0.0, remaining_seconds),
            _timer_expired,
        )

    async def async_set_manual_duration_minutes(self, minutes: int) -> None:
        """Set manual duration in minutes."""
        self._manual_duration_minutes = max(1, int(minutes))
        self._timer_duration = _format_timedelta(timedelta(minutes=self._manual_duration_minutes))
        self._async_notify_listeners()
        self.async_write_ha_state()
        _LOGGER.info("EcoThermostat %s manual duration set to %d min (%s)", self.entity_id or self.name, self._manual_duration_minutes, self._timer_duration)

    async def async_set_timer_duration(self, duration: timedelta):
        """Set Timer Duration SERVICE."""
        minutes = int(duration.total_seconds() // 60)
        await self.async_set_manual_duration_minutes(minutes)

    def _cancel_waiting_temp_timer(self) -> None:
        """Cancel the 10-minute waiting temp timer if running."""
        if self._unsub_waiting_temp is not None:
            self._unsub_waiting_temp()
            self._unsub_waiting_temp = None

    def _get_associated_window_entities(self) -> list[str]:
        """Get child entity_ids from the configured window binary_sensor if it is a group."""
        if not self._window_sensor:
            return []
        st = self.hass.states.get(self._window_sensor)
        if st and (eids := st.attributes.get(ATTR_ENTITY_ID)):
            if isinstance(eids, (list, tuple, set)):
                return [str(e) for e in eids]
            if isinstance(eids, str):
                return [e.strip() for e in eids.split(",") if e.strip()]
        return []

    def _get_entity_open_delay(self, entity_id: str) -> int:
        """Return the delay in seconds according to whether the entity is a door (30s) or window (5s)."""
        search_text = entity_id.lower()
        st = self.hass.states.get(entity_id)
        if st and (fname := st.attributes.get("friendly_name")):
            search_text += f" {str(fname).lower()}"

        if "puerta" in search_text:
            return DEFAULT_DOOR_OPEN_DELAY_SECONDS
        return DEFAULT_WINDOW_OPEN_DELAY_SECONDS

    def _cancel_all_pending_open_timers(self) -> None:
        """Cancel all pending open grace timers."""
        for unsub in self._pending_open_timers.values():
            unsub()
        self._pending_open_timers.clear()

    async def async_set_hvac_state(self, hvac_state: HVACState):
        """Set HVAC state SERVICE."""
        newstate = hvac_state
        oldstate = self._hvac_state
        if newstate == oldstate:
            return

        self._cancel_all_pending_open_timers()

        timer_state = self.hass.states.get(self._manual_timer) if self._manual_timer else None

        if self._target_temp_before is None:
            self._target_temp_before = self._target_temp

        # Manage HVACStatePrevious: only store base states (never window-open or waiting-temp)
        if oldstate in VALID_PREVIOUS_HVAC_STATES and newstate not in VALID_PREVIOUS_HVAC_STATES:
            self._hvac_state_previous = oldstate
        elif newstate in VALID_PREVIOUS_HVAC_STATES:
            self._hvac_state_previous = newstate

        self._hvac_state = newstate

        if newstate == HVACState.MANUAL:
            if self.ac_mode:
                self._hvac_mode = HVACMode.COOL
            else:
                self._hvac_mode = HVACMode.HEAT

            if oldstate == HVACState.HOME_CLOSED and self._target_temp_before is not None:
                await self._async_set_temperature(self._target_temp_before)
                self._target_temp_before = None

            now = dt_util.utcnow()
            if self._manual_timer_end is not None and now < self._manual_timer_end:
                remaining_seconds = (self._manual_timer_end - now).total_seconds()
            else:
                self._manual_remaining_seconds = float(self._manual_duration_minutes * 60)
                self._manual_timer_end = now + timedelta(seconds=self._manual_remaining_seconds)
                remaining_seconds = self._manual_remaining_seconds

            self._schedule_internal_timer(remaining_seconds)

            if timer_state and timer_state.state != STATUS_ACTIVE:
                await self._async_manual_timer_start()

            self._async_notify_listeners()

        elif newstate == HVACState.AUTO:
            if self.ac_mode:
                self._hvac_mode = HVACMode.COOL
            else:
                self._hvac_mode = HVACMode.HEAT

            self._target_temp_before = None

            self._cancel_internal_timer()
            self._manual_timer_end = None
            self._manual_remaining_seconds = 0.0

            if timer_state and timer_state.state != STATUS_IDLE:
                await self._async_manual_timer_cancel()

            await self._async_control_schedules()
            self._async_notify_listeners()

        elif newstate == HVACState.WINDOW_OPEN:
            self._cancel_waiting_temp_timer()
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()

            # The manual timer is NOT canceled or extended; its original deadline continues running.
            self._async_notify_listeners()

        elif newstate == HVACState.WAITING_TEMP:
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
            self._async_notify_listeners()

        elif newstate == HVACState.HOME_CLOSED:
            self._cancel_waiting_temp_timer()
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()

            self._target_temp_before = self._target_temp
            temp_away = self._presets[PRESET_AWAY]
            await self._async_set_temperature(temp_away)

            self._cancel_internal_timer()
            self._manual_timer_end = None
            self._manual_remaining_seconds = 0.0

            if timer_state and timer_state.state != STATUS_IDLE:
                await self._async_manual_timer_cancel()

            self._async_notify_listeners()

        elif newstate == HVACState.OFF:
            self._cancel_waiting_temp_timer()
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()

            self._cancel_internal_timer()
            self._manual_timer_end = None
            self._manual_remaining_seconds = 0.0

            if timer_state and timer_state.state != STATUS_IDLE:
                await self._async_manual_timer_cancel()

            self._async_notify_listeners()

        await self._async_control_heating(force=True)
        self.async_write_ha_state()
        _LOGGER.info("OK Service Set HVAC State to: %s", self._hvac_state)

    async def _async_window_sensor_changed(self, event):
        """Handle window/door binary_sensor state changes."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        if not self._child_window_sensors:
            self._child_window_sensors = self._get_associated_window_entities()

        if new_state.state in (STATE_ON, "on"):
            if self._hvac_state == HVACState.WINDOW_OPEN:
                return

            target_entity = entity_id or self._window_sensor
            if entity_id == self._window_sensor and self._child_window_sensors:
                on_children = [
                    cid for cid in self._child_window_sensors
                    if self.hass.states.is_state(cid, STATE_ON)
                ]
                if on_children:
                    target_entity = on_children[-1]

            if unsub := self._pending_open_timers.pop(target_entity, None):
                unsub()

            delay = self._get_entity_open_delay(target_entity)

            @callback
            def _open_delay_expired(_=None):
                self._pending_open_timers.pop(target_entity, None)
                is_still_on = self.hass.states.is_state(target_entity, STATE_ON) or (
                    self._window_sensor and self.hass.states.is_state(self._window_sensor, STATE_ON)
                )
                if is_still_on:
                    _LOGGER.info(
                        "EcoThermostat %s: Grace period (%ds) expired for %s. Setting state to WINDOW_OPEN",
                        self.entity_id or self.name,
                        delay,
                        target_entity,
                    )
                    self._cancel_all_pending_open_timers()
                    self.hass.create_task(self.async_set_hvac_state(HVACState.WINDOW_OPEN))

            self._pending_open_timers[target_entity] = async_call_later(
                self.hass,
                delay,
                _open_delay_expired,
            )
            _LOGGER.info(
                "EcoThermostat %s: Opened %s (delay: %ds). Grace timer started.",
                self.entity_id or self.name,
                target_entity,
                delay,
            )

        elif new_state.state in (STATE_OFF, "off"):
            if entity_id and (unsub := self._pending_open_timers.pop(entity_id, None)):
                unsub()
                _LOGGER.info(
                    "EcoThermostat %s: %s closed before grace timer expired. Cancelled timer.",
                    self.entity_id or self.name,
                    entity_id,
                )

            if entity_id == self._window_sensor:
                self._cancel_all_pending_open_timers()

            if self._hvac_state == HVACState.WINDOW_OPEN:
                all_eids = self._child_window_sensors or [self._window_sensor]
                any_open = any(self.hass.states.is_state(eid, STATE_ON) for eid in all_eids if eid)
                if self._window_sensor and self.hass.states.is_state(self._window_sensor, STATE_ON):
                    any_open = True

                if not any_open:
                    _LOGGER.info(
                        "EcoThermostat %s: All window/door sensors closed. Executing recovery.",
                        self.entity_id or self.name,
                    )
                    await self._async_handle_window_closed()
                else:
                    _LOGGER.info(
                        "EcoThermostat %s: %s closed, but other window/door sensors remain open.",
                        self.entity_id or self.name,
                        entity_id,
                    )

    async def _async_handle_window_open(self):
        """Handle window opened event."""
        if self._hvac_state == HVACState.WINDOW_OPEN:
            return

        _LOGGER.info(
            "EcoThermostat %s: Window opened. Setting state to WINDOW_OPEN",
            self.entity_id or self.name,
        )
        self._cancel_all_pending_open_timers()
        self._cancel_waiting_temp_timer()

        if self._hvac_state in VALID_PREVIOUS_HVAC_STATES:
            self._hvac_state_previous = self._hvac_state

        self._hvac_state = HVACState.WINDOW_OPEN
        self._hvac_mode = HVACMode.OFF

        if self._is_device_active:
            await self._async_heater_turn_off()

        self._async_notify_listeners()
        self.async_write_ha_state()

    async def _async_handle_window_closed(self):
        """Handle window closed event."""
        self._cancel_all_pending_open_timers()
        if self._hvac_state != HVACState.WINDOW_OPEN:
            return

        _LOGGER.info(
            "EcoThermostat %s: Window closed. Evaluating recovery",
            self.entity_id or self.name,
        )

        is_below = False
        if self._cur_temp is not None and self._target_temp is not None:
            if self._cur_temp < (self._target_temp - 0.2):
                is_below = True

        if is_below:
            _LOGGER.info(
                "EcoThermostat %s: Current temp %.1f < Target temp %.1f - 0.2. Setting state to WAITING_TEMP (10 min timer)",
                self.entity_id or self.name,
                self._cur_temp,
                self._target_temp,
            )
            self._hvac_state = HVACState.WAITING_TEMP
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()

            self._cancel_waiting_temp_timer()

            @callback
            def _waiting_expired(_=None):
                self._unsub_waiting_temp = None
                _LOGGER.info(
                    "EcoThermostat %s: Waiting temp timer (10 min) expired. Restoring previous state",
                    self.entity_id or self.name,
                )
                self.hass.create_task(self._async_restore_previous_state())

            self._unsub_waiting_temp = async_call_later(
                self.hass,
                600,
                _waiting_expired,
            )
            self._async_notify_listeners()
            self.async_write_ha_state()
        else:
            _LOGGER.info(
                "EcoThermostat %s: Temperature recovered or not below threshold. Restoring previous state immediately",
                self.entity_id or self.name,
            )
            await self._async_restore_previous_state()

    async def _async_restore_previous_state(self):
        """Restore HVACState from HVACStatePrevious."""
        self._cancel_all_pending_open_timers()
        self._cancel_waiting_temp_timer()

        target_state = self._hvac_state_previous
        if target_state not in VALID_PREVIOUS_HVAC_STATES:
            target_state = HVACState.AUTO

        if target_state == HVACState.MANUAL:
            if self._manual_timer_end is not None and dt_util.utcnow() >= self._manual_timer_end:
                _LOGGER.info(
                    "EcoThermostat %s: Manual timer expired while window was open/waiting. Transitioning to AUTO",
                    self.entity_id or self.name,
                )
                target_state = HVACState.AUTO
                self._cancel_internal_timer()
                self._manual_timer_end = None
                self._manual_remaining_seconds = 0.0

        _LOGGER.info(
            "EcoThermostat %s: Restoring state from %s to %s",
            self.entity_id or self.name,
            self._hvac_state,
            target_state,
        )

        await self.async_set_hvac_state(target_state)

    async def _check_window_initial_state(self):
        """Evaluate window sensor state on startup."""
        if not self._window_sensor:
            if self._hvac_state in (HVACState.WINDOW_OPEN, HVACState.WAITING_TEMP):
                await self._async_restore_previous_state()
            return

        self._child_window_sensors = self._get_associated_window_entities()

        all_eids = self._child_window_sensors or [self._window_sensor]
        any_open = any(self.hass.states.is_state(eid, STATE_ON) for eid in all_eids if eid)
        if self._window_sensor and self.hass.states.is_state(self._window_sensor, STATE_ON):
            any_open = True

        if any_open:
            if self._hvac_state != HVACState.WINDOW_OPEN:
                if self._hvac_state in VALID_PREVIOUS_HVAC_STATES:
                    self._hvac_state_previous = self._hvac_state
                self._hvac_state = HVACState.WINDOW_OPEN
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
            self._async_notify_listeners()
            self.async_write_ha_state()
        else:
            if self._hvac_state == HVACState.WINDOW_OPEN:
                await self._async_handle_window_closed()
            elif self._hvac_state == HVACState.WAITING_TEMP:
                if (
                    self._cur_temp is not None
                    and self._target_temp is not None
                    and self._cur_temp >= self._target_temp
                ):
                    await self._async_restore_previous_state()
                else:
                    self._cancel_waiting_temp_timer()

                    @callback
                    def _waiting_expired(_=None):
                        self._unsub_waiting_temp = None
                        self.hass.create_task(self._async_restore_previous_state())

                    self._unsub_waiting_temp = async_call_later(
                        self.hass, 600, _waiting_expired
                    )
            else:
                if self._hvac_state in (HVACState.AUTO, HVACState.MANUAL):
                    self._hvac_mode = HVACMode.COOL if self.ac_mode else HVACMode.HEAT
                else:
                    self._hvac_mode = HVACMode.OFF
                self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._cancel_internal_timer()
        self._cancel_waiting_temp_timer()
        self._cancel_all_pending_open_timers()
        await super().async_will_remove_from_hass()

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if HVACMode.HEAT in self.hvac_modes:
            await self.async_set_hvac_mode(HVACMode.HEAT)
        elif HVACMode.COOL in self.hvac_modes:
            await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
        await self._async_set_temperature(temperature, auto=False)

    async def _async_set_temperature(self, target_temp, auto=True) -> None:
        """Set new target temperature."""
        if target_temp is None or self._target_temp == target_temp:
            return
        self._target_temp_before = self._target_temp
        self._target_temp = target_temp
        self._heating_locked_since = None

        if not auto:
            await self.async_set_hvac_state(HVACState.MANUAL)

        await self._async_control_heating(force=True)
        self.async_write_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    @property
    def manual_timer(self):
        """Return the Timer for manual temperature set."""
        return self._manual_timer

    @property
    def max_time_on(self):
        """Return the MAX Time Switch is ON."""
        return self._max_time_on

    @property
    def hot_tolerance(self):
        """Returns the Hot tolerance."""
        return self._hot_tolerance

    @property
    def max_heating_locked(self):
        """Returns the Max Minutes Heating will be locked."""
        return self._max_heating_locked

    @property
    def calendar_holidays(self):
        """Returns the calendar entity containing the holidays."""
        return self._calendar_holidays

    @property
    def max_temp_jumps(self):
        """Return the Max temperatura Jumps."""
        return self._max_temp_jumps

    @property
    def prog_temp(self):
        """Return the temperature programation."""
        return self._prog_temp

    @property
    def prog_temp_holidays(self):
        """Return the temperature programation for holidays."""
        return self._prog_temp_holidays

    async def _async_sensor_changed(self, event):
        """Handle temperature changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)

        # Check if in WAITING_TEMP and temperature has reached target
        if self._hvac_state == HVACState.WAITING_TEMP:
            if self._cur_temp is not None and self._target_temp is not None:
                if self._cur_temp >= self._target_temp:
                    _LOGGER.info(
                        "EcoThermostat %s: Temperature recovered (%.1f >= %.1f). Exiting WAITING_TEMP early",
                        self.entity_id or self.name,
                        self._cur_temp,
                        self._target_temp,
                    )
                    self._cancel_waiting_temp_timer()
                    await self._async_restore_previous_state()
                    return

        await self._async_control_heating()
        self.async_write_ha_state()

    async def _check_switch_initial_state(self):
        """Prevent the device from keep running if HVACMode.OFF."""
        if self._hvac_mode == HVACMode.OFF and self._is_device_active:
            _LOGGER.warning(
                (
                    "The climate mode is OFF, but the switch device is ON. Turning off"
                    " device %s"
                ),
                self.heater_entity_id,
            )
            await self._async_heater_turn_off()

    async def _check_timer_initial_state(self):
        """Prevent the device from keeping MANUAL if timer is OFF."""
        timer_state = self.hass.states.get(self._manual_timer)
        if timer_state is None:
            return
        if timer_state.state == STATUS_IDLE:
            if self._hvac_state == HVACState.MANUAL:
                _LOGGER.warning(
                    (
                        "The timer is IDLE, but the hvac state is MANUAL. Turning to AUTO"
                        " timer %s"
                    ),
                    self._manual_timer,
                )
                await self.async_set_hvac_state(HVACState.AUTO)
        elif timer_state.state == STATUS_ACTIVE and self._hvac_state != HVACState.MANUAL:
            _LOGGER.warning(
                (
                    "The timer is ACTIVE, but the hvac state is not MANUAL. Turning to MANUAL"
                    " timer %s"
                ),
                self._manual_timer,
            )
            await self.async_set_hvac_state(HVACState.MANUAL)

    @callback
    def _async_switch_changed(self, event):
        """Handle heater switch state changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        if old_state is None:
            self.hass.create_task(self._check_switch_initial_state())

        if new_state.state == STATE_ON:
            self._attr_poweron_since = self._get_time_now()
        else:
            self._attr_poweron_since = None

        self.async_write_ha_state()

    async def _async_timer_changed(self, event):
        """Handle manual timer state changes."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        if old_state is None:
            self.hass.create_task(self._check_timer_initial_state())

        if new_state.state == STATUS_IDLE and self._hvac_state == HVACState.MANUAL:
            await self.async_set_hvac_state(HVACState.AUTO)
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if math.isnan(cur_temp) or math.isinf(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self, time=None, force=False):
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (
                self._cur_temp,
                self._target_temp,
            ):
                self._active = True
                _LOGGER.info(
                    (
                        "Obtained current and target temperature. "
                        "Eco thermostat active. %s, %s"
                    ),
                    self._cur_temp,
                    self._target_temp,
                )

            if not self._active or self._hvac_mode == HVACMode.OFF:
                return

            if self._hvac_state not in (HVACState.AUTO, HVACState.MANUAL):
                if self._is_device_active:
                    await self._async_heater_turn_off()
                return

            # If the `force` argument is True, we
            # ignore `min_cycle_duration`.
            # If the `time` argument is not none, we were invoked for
            # keep-alive purposes, and `min_cycle_duration` is irrelevant.
            if not force and time is None and self.min_cycle_duration:
                if self._is_device_active:
                    current_state = STATE_ON
                else:
                    current_state = HVACMode.OFF
                try:
                    long_enough = condition.state(
                        self.hass,
                        self.heater_entity_id,
                        current_state,
                        self.min_cycle_duration,
                    )
                except ConditionError:
                    long_enough = False

                if not long_enough:
                    return

            too_cold = self._target_temp >= (self._cur_temp + self._cold_tolerance)
            too_hot = self._cur_temp >= (self._target_temp + self._hot_tolerance)
            if self._is_device_active:
                if (self.ac_mode and too_cold) or (not self.ac_mode and too_hot):
                    _LOGGER.info("Turning off heater %s", self.heater_entity_id)
                    self._heating_locked_since = self._get_time_now()
                    await self._async_heater_turn_off()
                elif not self.ac_mode and too_cold:
                    self._heating_locked_since = self._get_time_now()
                    await self.async_update_ha_state(True)
                    # await self.async_write_ha_state()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning on heater heater %s",
                        self.heater_entity_id,
                    )
                    await self._async_heater_turn_on()
            else:  # noqa: PLR5501
                if (self.ac_mode and too_hot) or (not self.ac_mode and too_cold):
                    if self._heating_locked_since is None:
                        _LOGGER.info("Turning on heater %s", self.heater_entity_id)
                        self._hot_tolerance_update()
                        self._heating_locked_since = self._get_time_now()
                        await self._async_heater_turn_on()

                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning off heater %s", self.heater_entity_id
                    )
                    await self._async_heater_turn_off()

    def _init_timer_duration(self):
        """Init Timer Duration."""
        if self._timer_duration is None and self._manual_timer is not None:
            timer_state = self.hass.states.get(self._manual_timer)
            if timer_state is not None:
                self._timer_duration = timer_state.attributes.get(ATTR_DURATION)
        if self._timer_duration is not None:
            try:
                parts = str(self._timer_duration).split(":")
                if len(parts) == 3:
                    self._manual_duration_minutes = int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 2:
                    self._manual_duration_minutes = int(parts[0]) * 60 + int(parts[1])
            except Exception:
                pass
        elif self._manual_duration_minutes:
            self._timer_duration = _format_timedelta(timedelta(minutes=self._manual_duration_minutes))

    def _hot_tolerance_update(self):
        """Update hot tolerance based on max_temp_jumps."""
        delta = self._cur_temp - self._target_temp
        max_tolerance = self._get_max_tolerance(delta)

        if max_tolerance > self._min_hot_tolerance:
            max_tolerance = self._min_hot_tolerance

        self._hot_tolerance = max_tolerance

        _LOGGER.info("Hot Tolerance Update - %s", self._hot_tolerance)

    def _get_max_tolerance(self, delta):
        """Return max tolerance from delta."""
        if self._max_temp_jumps:
            for jump in self._max_temp_jumps:
                if delta <= (jump.get("delta") + 0.0001):
                    return jump.get("tolerance")
            return 0.0

    async def _async_control_heating_lock(self, other):
        """Control how minutes heating is locked."""

        if self._heating_locked_since is not None:
            delta = self._get_time_now() - self._heating_locked_since
            if delta >= self._max_heating_locked:
                self._heating_locked_since = None
                await self._async_control_heating(force=True)

    def _get_time_now(self):
        """Local datetime now."""
        return dt_util.as_local(dt_util.utcnow())

    async def _async_every_minute_event(self, other=None):
        """Every minute event."""
        await self._async_control_schedules()
        await self._async_control_power_on()

    async def _async_control_power_on(self, other=None):
        """Control power on time."""

        if self._max_time_on is None:
            return

        heater_entity = self.hass.states.get(self.heater_entity_id)
        if heater_entity is None:
            return

        if heater_entity.state != STATE_ON:
            return

        now = self._get_time_now()
        if self._attr_poweron_since is None:
            self._attr_poweron_since = dt_util.as_local(heater_entity.last_changed)

        delta = now - self._attr_poweron_since
        if delta >= self._max_time_on:
            _LOGGER.info("Turning off heater %s, max time on", self.heater_entity_id)
            self._heating_locked_since = self._get_time_now()
            await self._async_heater_turn_off()

    async def _async_control_schedules(self, other=None):
        """Control temperature schedules."""
        if self._hvac_state != HVACState.AUTO:
            return

        now = self._get_time_now()
        self._attr_is_week_holiday = now.weekday() in (5, 6)
        self._attr_is_calendar_holiday = self.hass.states.is_state(
            self._calendar_holidays, STATE_ON
        )
        self._attr_is_holiday = (
            self._attr_is_week_holiday or self._attr_is_calendar_holiday
        )

        schedules = self._schedule_temp
        if self._attr_is_holiday:
            schedules = self._schedule_temp_holidays

        temp, i = self._calc_temperature_auto(schedules, now)
        await self._async_set_temperature(temp, auto=True)

        next_temp, next_time = self._calc_temperature_next(schedules, i + 1)
        self._attr_next_temperature = next_temp
        self._attr_next_temperature_time = next_time

    def _calc_temperature_auto(self, schedules, now) -> tuple[float, int]:
        """Calc scheduled temperature and position of schedule."""
        temp = 19.5
        position = 0
        if schedules:
            for schedule in schedules:
                start = cv.time(schedule.get("start"))
                end = cv.time(schedule.get("end"))
                if start <= now.time() and end >= now.time():
                    temp = schedule.get("temp")
                    return temp, position
                position = position + 1

        return temp, position

    def _calc_temperature_next(self, schedules, position) -> tuple[float, datetime]:
        """Calc temperature and temperature start time."""
        next_temp = None
        next_time = None
        if schedules:
            if position >= len(schedules):
                position = 0
            schedule = schedules[position]
            next_temp = schedule.get("temp")
            next_time = cv.time(schedule.get("start"))

        return next_temp, next_time

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        if not self.hass.states.get(self.heater_entity_id):
            return None

        return self.hass.states.is_state(self.heater_entity_id, STATE_ON)

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_ON, data, context=self._context
        )

    async def _async_heater_turn_off(self):
        """Turn heater toggleable device off."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_OFF, data, context=self._context
        )

    async def _async_manual_timer_start(self):
        """Start manual timer."""
        self._init_timer_duration()

        data = {
            ATTR_ENTITY_ID: self._manual_timer,
            ATTR_DURATION: self._timer_duration,
        }
        await self.hass.services.async_call(
            "timer", "start", data, context=self._context
        )

    async def _async_manual_timer_cancel(self):
        """Cancel manual timer."""
        data = {ATTR_ENTITY_ID: self._manual_timer}
        await self.hass.services.async_call(
            "timer", "cancel", data, context=self._context
        )

    async def _async_manual_timer_pause(self):
        """Pause manual timer."""
        data = {ATTR_ENTITY_ID: self._manual_timer}
        await self.hass.services.async_call(
            "timer", "pause", data, context=self._context
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode not in (self.preset_modes or []):
            raise ValueError(
                f"Got unsupported preset_mode {preset_mode}. Must be one of"
                f" {self.preset_modes}"
            )
        if preset_mode == self._attr_preset_mode:
            # I don't think we need to call async_write_ha_state if we didn't change the state
            return
        if preset_mode == PRESET_NONE:
            self._attr_preset_mode = PRESET_NONE
            self._target_temp = self._saved_target_temp
            await self._async_control_heating(force=True)
        else:
            if self._attr_preset_mode == PRESET_NONE:
                self._saved_target_temp = self._target_temp
            self._attr_preset_mode = preset_mode
            self._target_temp = self._presets[preset_mode]
            await self._async_control_heating(force=True)

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Platform specific attributes."""

        heating_locked_since = "None"
        if self._heating_locked_since is not None:
            heating_locked_since = self._heating_locked_since.strftime(
                "%d/%m/%Y, %H:%M:%S"
            )

        attr_poweron_since = "None"
        if self._attr_poweron_since is not None:
            attr_poweron_since = self._attr_poweron_since.strftime("%d/%m/%Y, %H:%M:%S")

        _max_heating_locked = None
        if self._max_heating_locked is not None:
            _max_heating_locked = _format_timedelta(self._max_heating_locked)

        timer_finishes_at = (
            self._manual_timer_end.isoformat() if self._manual_timer_end is not None else None
        )
        timer_remaining_seconds = 0
        if self._manual_timer_end is not None:
            timer_remaining_seconds = max(
                0, int((self._manual_timer_end - dt_util.utcnow()).total_seconds())
            )
        return {
            "hot_tolerance": self._hot_tolerance,
            "cold_tolerance": self._cold_tolerance,
            "heating_locked_since": heating_locked_since,
            "hvac_state": self._hvac_state,
            "hvac_state_previous": self._hvac_state_previous,
            "window_sensor": self._window_sensor,
            "timer_duration": self._timer_duration,
            "timer_finishes_at": timer_finishes_at,
            "manual_duration_minutes": self._manual_duration_minutes,
            "timer_remaining_seconds": timer_remaining_seconds,
            "is_week_holiday": self._attr_is_week_holiday,
            "is_calendar_holiday": self._attr_is_calendar_holiday,
            "is_holiday": self._attr_is_holiday,
            "next_temperature": self._attr_next_temperature,
            "next_temperature_time": self._attr_next_temperature_time,
            "poweron_since": attr_poweron_since,
            "max_heating_locked": _max_heating_locked,
        }
