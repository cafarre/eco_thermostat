"""Adds support for eco thermostat units."""
from __future__ import annotations

import asyncio
from datetime import datetime, time as time_sys, timedelta
import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import (
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
from homeassistant.components.timer import ATTR_DURATION, STATUS_ACTIVE, STATUS_IDLE
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
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, CoreState, HomeAssistant, callback
from homeassistant.exceptions import ConditionError
from homeassistant.helpers import condition, entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt_util

from . import DOMAIN, PLATFORMS
from .const import HVACState

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


def time_validation(value: Any) -> time_sys:
    """Time valiadtion."""
    # parts = str(value).split(":")
    # if len(parts) < 2:
    #     return None

    # try:
    #     hour = int(parts[0])
    #     minute = int(parts[1])
    #     second = int(parts[2]) if len(parts) > 2 else 0
    #     return dt.time(hour, minute, second)
    # except ValueError:
    #     # ValueError if value cannot be converted to an int or not in range
    #     return None
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


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the eco thermostat platform."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    platform = entity_platform.async_get_current_platform()
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

    name = config.get(CONF_NAME)
    heater_entity_id = config.get(CONF_HEATER)
    sensor_entity_id = config.get(CONF_SENSOR)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    ac_mode = config.get(CONF_AC_MODE)
    min_cycle_duration = config.get(CONF_MIN_DUR)
    cold_tolerance = config.get(CONF_COLD_TOLERANCE)
    hot_tolerance = config.get(CONF_HOT_TOLERANCE)
    keep_alive = config.get(CONF_KEEP_ALIVE)
    initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
    presets = {
        key: config[value] for key, value in CONF_PRESETS.items() if value in config
    }
    precision = config.get(CONF_PRECISION)
    target_temperature_step = config.get(CONF_TEMP_STEP)
    unit = hass.config.units.temperature_unit
    unique_id = config.get(CONF_UNIQUE_ID)

    # new fields
    min_hot_tolerance = config.get(CONF_MIN_HOT_TOLERANCE)
    max_temp_jumps = config.get(CONF_MAX_TEMP_JUMPS)
    max_heating_locked = config.get(CONF_MAX_HEATING_LOCKED)
    manual_timer = config.get(CONF_MANUAL_TIMER)
    calendar_holidays = config.get(CONF_CALENDAR_HOLIDAYS)
    schedule_temp = config.get(CONF_SCHEDULE_TEMP)
    schedule_temp_holidays = config.get(CONF_SCHEDULE_TEMP_HOLIDAY)
    max_time_on = config.get(CONF_MAX_TIME_ON)

    async_add_entities(
        [
            EcoThermostat(
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
            )
        ]
    )


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
        self._attr_temperature_unit = unit
        self._attr_unique_id = unique_id
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        if len(presets):
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE] + list(presets.keys())
        else:
            self._attr_preset_modes = [PRESET_NONE]
        self._presets = presets

        # New fields
        self._min_hot_tolerance = min_hot_tolerance
        self._max_temp_jumps = max_temp_jumps
        self._heating_locked_since = None
        self._max_heating_locked = max_heating_locked
        self._hvac_state = HVACState.AUTO
        self._timer_duration = None
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
                self._hvac_mode = old_state.state

            # if old_state.attributes.get(ATTR_HVAC_STATE) is not None:
            #    self._hvac_state = old_state.attributes.get(ATTR_HVAC_STATE)

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

        # Set default state to off
        if not self._hvac_mode:
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
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_state(self):
        """Return current state."""
        return self._hvac_state

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
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
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
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_timer_duration(self, duration: timedelta):
        """Set Timer Duration SERVICE."""
        self._timer_duration = _format_timedelta(duration)
        self.async_write_ha_state()
        _LOGGER.info("OK Service Set Timer Duration to: %s", self._timer_duration)

    async def async_set_hvac_state(self, hvac_state: HVACState):
        """Set HVAC state SERVICE."""
        newstate = hvac_state
        oldstate = self._hvac_state
        if newstate == oldstate:
            return

        timer_state = self.hass.states.get(self._manual_timer)

        if self._target_temp_before is None:
            self._target_temp_before = self._target_temp

        if self._hvac_mode_before is None:
            self._hvac_mode_before = HVACMode.HEAT

        self._hvac_state = newstate
        if newstate == HVACState.MANUAL:
            self._hvac_state_before = None
            if oldstate == HVACState.WINDOW_OPEN:
                await self.async_set_hvac_mode(self._hvac_mode_before)
            elif oldstate == HVACState.HOME_CLOSED:
                await self.async_set_hvac_mode(self._hvac_mode_before)
                await self._async_set_temperature(self._target_temp_before)
                self._target_temp_before = None

            if timer_state.state != STATUS_ACTIVE:
                await self._async_manual_timer_start()

        elif newstate == HVACState.AUTO:
            self._hvac_state_before = None
            if oldstate == HVACState.WINDOW_OPEN:
                await self.async_set_hvac_mode(self._hvac_mode_before)
            if oldstate == HVACState.HOME_CLOSED:
                await self.async_set_hvac_mode(self._hvac_mode_before)
            else:
                self._target_temp_before = None

            if timer_state.state != STATUS_IDLE:
                await self._async_manual_timer_cancel()

        elif newstate == HVACState.WINDOW_OPEN:
            self._hvac_mode_before = self._hvac_mode
            self._hvac_state_before = oldstate
            self._target_temp_before = self._target_temp
            await self.async_set_hvac_mode(HVACMode.OFF)
            if timer_state.state == STATUS_ACTIVE:
                await self._async_manual_timer_pause()

        elif newstate == HVACState.HOME_CLOSED:
            self._hvac_mode_before = self._hvac_mode
            self._hvac_state_before = oldstate
            self._target_temp_before = self._target_temp
            temp_away = self._presets[PRESET_AWAY]
            await self._async_set_temperature(temp_away)
            if timer_state.state != STATUS_IDLE:
                await self._async_manual_timer_cancel()

        await self._async_control_heating(force=True)
        self.async_write_ha_state()
        _LOGGER.info("OK Service Set HVAC State to: %s", self._hvac_state)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
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
        """Prevent the device from keep MANUAL if timer is OFF."""
        timer_state = self.hass.states.get(self._manual_timer)
        if timer_state == STATUS_IDLE:
            if self._hvac_state == HVACMode.MANUAL:
                _LOGGER.warning(
                    (
                        "The timer is IDLE, but the hvac state is MANUAL. Turning to AUTO"
                        " timer %s"
                    ),
                    self._manual_timer,
                )
                await self.async_set_hvac_state(HVACState.AUTO)
        elif self._hvac_state != HVACMode.MANUAL:
            _LOGGER.warning(
                (
                    "The timer is IDLE, but the hvac state is MANUAL. Turning to AUTO"
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

    @callback
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

        if self._max_heating_locked is not None:
            _max_heating_locked = _format_timedelta(self._max_heating_locked)

        return {
            "hot_tolerance": self._hot_tolerance,
            "cold_tolerance": self._cold_tolerance,
            "heating_locked_since": heating_locked_since,
            "hvac_state": self._hvac_state,
            "timer_duration": self._timer_duration,
            "is_week_holiday": self._attr_is_week_holiday,
            "is_calendar_holiday": self._attr_is_calendar_holiday,
            "is_holiday": self._attr_is_holiday,
            "next_temperature": self._attr_next_temperature,
            "next_temperature_time": self._attr_next_temperature_time,
            "poweron_since": attr_poweron_since,
            "max_heating_locked": _max_heating_locked,
        }
