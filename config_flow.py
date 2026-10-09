"""Config flow for Eco Thermostat integration."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time as time_sys, timedelta
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.climate import HVACMode
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import (
    CONF_NAME,
    CONF_UNIQUE_ID,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_AC_MODE,
    CONF_CALENDAR_HOLIDAYS,
    CONF_COLD_TOLERANCE,
    CONF_HEATER,
    CONF_HOT_TOLERANCE,
    CONF_INITIAL_HVAC_MODE,
    CONF_KEEP_ALIVE,
    CONF_MANUAL_TIMER,
    CONF_MAX_HEATING_LOCKED,
    CONF_MAX_TEMP,
    CONF_MAX_TEMP_JUMPS,
    CONF_MAX_TIME_ON,
    CONF_MIN_CYCLE_DURATION,
    CONF_MIN_HOT_TOLERANCE,
    CONF_MIN_TEMP,
    CONF_PRECISION,
    CONF_PRESETS,
    CONF_SCHEDULE_TEMP,
    CONF_SCHEDULE_TEMP_HOLIDAY,
    CONF_SENSOR,
    CONF_TARGET_TEMP_STEP,
    DEFAULT_NAME,
    DEFAULT_TOLERANCE,
    DOMAIN,
)

PRECISION_OPTIONS = [
    selector.SelectOptionDict(value=str(PRECISION_TENTHS), label="0.1"),
    selector.SelectOptionDict(value=str(PRECISION_HALVES), label="0.5"),
    selector.SelectOptionDict(value=str(PRECISION_WHOLE), label="1.0"),
]

HVAC_MODE_OPTIONS = [
    selector.SelectOptionDict(value=HVACMode.OFF.value, label="Off"),
    selector.SelectOptionDict(value=HVACMode.HEAT.value, label="Heat"),
    selector.SelectOptionDict(value=HVACMode.COOL.value, label="Cool"),
]


def _serialize_for_entry(val: Any) -> Any:
    """Recursively convert timedeltas and times into JSON-serializable structures."""
    if isinstance(val, timedelta):
        return {"seconds": int(val.total_seconds())}
    if isinstance(val, (time_sys, datetime)):
        return val.strftime("%H:%M:%S")
    if isinstance(val, dict):
        return {k: _serialize_for_entry(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_serialize_for_entry(v) for v in val]
    return val


class EcoThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eco Thermostat."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step (Core Thermostat settings)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            # Use unique_id based on heater or sensor if not set
            unique_id = f"eco_{user_input[CONF_HEATER]}_{user_input[CONF_SENSOR]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                vol.Required(CONF_HEATER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
                ),
                vol.Required(CONF_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=SENSOR_DOMAIN, device_class=SensorDeviceClass.TEMPERATURE
                    )
                ),
                vol.Optional(CONF_AC_MODE, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_MIN_TEMP, default=16.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=50.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_MAX_TEMP, default=25.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=50.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_COLD_TOLERANCE, default=DEFAULT_TOLERANCE
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_HOT_TOLERANCE, default=-0.1
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_TARGET_TEMP_STEP, default=str(PRECISION_TENTHS)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PRECISION_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_PRECISION, default=str(PRECISION_TENTHS)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PRECISION_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_INITIAL_HVAC_MODE, default=HVACMode.OFF.value
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=HVAC_MODE_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the presets step."""
        if user_input is not None:
            # Filter out None values
            presets_data = {k: v for k, v in user_input.items() if v is not None}
            self._data.update(presets_data)
            return await self.async_step_eco_settings()

        min_temp = self._data.get(CONF_MIN_TEMP, 16.0)
        max_temp = self._data.get(CONF_MAX_TEMP, 25.0)

        schema = vol.Schema(
            {
                vol.Optional(CONF_PRESETS["away"], default=17.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_PRESETS["comfort"], default=21.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_PRESETS["home"], default=20.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_PRESETS["sleep"], default=18.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )

        return self.async_show_form(step_id="presets", data_schema=schema)

    async def async_step_eco_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the Eco specific features and schedules step."""
        if user_input is not None:
            eco_data = {k: v for k, v in user_input.items() if v is not None}
            self._data.update(eco_data)
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_MANUAL_TIMER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="timer")
                ),
                vol.Optional(CONF_CALENDAR_HOLIDAYS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar")
                ),
                vol.Optional(CONF_MIN_CYCLE_DURATION): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(CONF_MAX_TIME_ON): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(CONF_MAX_HEATING_LOCKED): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(
                    CONF_MIN_HOT_TOLERANCE, default=-0.1
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_MAX_TEMP_JUMPS): selector.ObjectSelector(),
                vol.Optional(CONF_SCHEDULE_TEMP): selector.ObjectSelector(),
                vol.Optional(CONF_SCHEDULE_TEMP_HOLIDAY): selector.ObjectSelector(),
            }
        )

        return self.async_show_form(step_id="eco_settings", data_schema=schema)

    async def async_step_import(
        self, import_config: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Import a YAML configuration."""
        unique_id = import_config.get(CONF_UNIQUE_ID)
        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        data = _serialize_for_entry(dict(import_config))
        return self.async_create_entry(
            title=data.get(CONF_NAME, DEFAULT_NAME),
            data=data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EcoThermostatOptionsFlowHandler()


class EcoThermostatOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Eco Thermostat."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._options: dict[str, Any] = {}

    def _get_val(self, key: str, default: Any = None) -> Any:
        """Get value from options or fall back to config entry data."""
        if key in self.config_entry.options:
            return self.config_entry.options[key]
        return self.config_entry.data.get(key, default)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage core settings."""
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HEATER, default=self._get_val(CONF_HEATER)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
                ),
                vol.Required(
                    CONF_SENSOR, default=self._get_val(CONF_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=SENSOR_DOMAIN, device_class=SensorDeviceClass.TEMPERATURE
                    )
                ),
                vol.Optional(
                    CONF_AC_MODE, default=self._get_val(CONF_AC_MODE, False)
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_MIN_TEMP, default=self._get_val(CONF_MIN_TEMP, 16.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=50.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_MAX_TEMP, default=self._get_val(CONF_MAX_TEMP, 25.0)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=50.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_COLD_TOLERANCE,
                    default=self._get_val(CONF_COLD_TOLERANCE, DEFAULT_TOLERANCE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_HOT_TOLERANCE,
                    default=self._get_val(CONF_HOT_TOLERANCE, -0.1),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_TARGET_TEMP_STEP,
                    default=str(self._get_val(CONF_TARGET_TEMP_STEP, PRECISION_TENTHS)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PRECISION_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_PRECISION,
                    default=str(self._get_val(CONF_PRECISION, PRECISION_TENTHS)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=PRECISION_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage presets."""
        if user_input is not None:
            self._options.update({k: v for k, v in user_input.items() if v is not None})
            return await self.async_step_eco_settings()

        min_temp = self._options.get(
            CONF_MIN_TEMP, self._get_val(CONF_MIN_TEMP, 16.0)
        )
        max_temp = self._options.get(
            CONF_MAX_TEMP, self._get_val(CONF_MAX_TEMP, 25.0)
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PRESETS["away"],
                    default=self._get_val(CONF_PRESETS["away"], 17.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PRESETS["comfort"],
                    default=self._get_val(CONF_PRESETS["comfort"], 21.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PRESETS["home"],
                    default=self._get_val(CONF_PRESETS["home"], 20.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PRESETS["sleep"],
                    default=self._get_val(CONF_PRESETS["sleep"], 18.5),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=min_temp, max=max_temp, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )

        return self.async_show_form(step_id="presets", data_schema=schema)

    async def async_step_eco_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage eco settings and schedules."""
        if user_input is not None:
            self._options.update({k: v for k, v in user_input.items() if v is not None})
            return self.async_create_entry(title="", data=self._options)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MANUAL_TIMER, default=self._get_val(CONF_MANUAL_TIMER)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="timer")
                ),
                vol.Optional(
                    CONF_CALENDAR_HOLIDAYS, default=self._get_val(CONF_CALENDAR_HOLIDAYS)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="calendar")
                ),
                vol.Optional(
                    CONF_MIN_CYCLE_DURATION, default=self._get_val(CONF_MIN_CYCLE_DURATION)
                ): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(
                    CONF_MAX_TIME_ON, default=self._get_val(CONF_MAX_TIME_ON)
                ): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(
                    CONF_MAX_HEATING_LOCKED, default=self._get_val(CONF_MAX_HEATING_LOCKED)
                ): selector.DurationSelector(
                    selector.DurationSelectorConfig(enable_day=False)
                ),
                vol.Optional(
                    CONF_MIN_HOT_TOLERANCE,
                    default=self._get_val(CONF_MIN_HOT_TOLERANCE, -0.1),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-5.0, max=5.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_MAX_TEMP_JUMPS, default=self._get_val(CONF_MAX_TEMP_JUMPS)
                ): selector.ObjectSelector(),
                vol.Optional(
                    CONF_SCHEDULE_TEMP, default=self._get_val(CONF_SCHEDULE_TEMP)
                ): selector.ObjectSelector(),
                vol.Optional(
                    CONF_SCHEDULE_TEMP_HOLIDAY,
                    default=self._get_val(CONF_SCHEDULE_TEMP_HOLIDAY),
                ): selector.ObjectSelector(),
            }
        )

        return self.async_show_form(step_id="eco_settings", data_schema=schema)
