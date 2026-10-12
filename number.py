"""Number platform for Eco Thermostat."""
from __future__ import annotations

import logging
from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN
from .climate import EcoThermostat

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eco Thermostat number entities."""
    thermostat: EcoThermostat | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if thermostat is None:
        _LOGGER.error("Thermostat not found for entry %s in number platform setup", entry.entry_id)
        return

    async_add_entities([EcoThermostatDurationNumber(thermostat)])


class EcoThermostatDurationNumber(RestoreNumber):
    """Number entity to control manual duration for Eco Thermostat."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 5.0
    _attr_native_max_value = 180.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, thermostat: EcoThermostat) -> None:
        """Initialize duration number entity."""
        self._thermostat = thermostat
        base_id = slugify(thermostat.name or "eco_thermostat")
        self.entity_id = f"number.{base_id}_duracion_manual"
        self._attr_unique_id = f"{thermostat.unique_id}_duracion_manual"
        self._attr_name = "Duración Manual"
        self._attr_native_value = float(thermostat.manual_duration_minutes)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info matching the climate entity."""
        return self._thermostat.device_info

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await super().async_added_to_hass()

        self.async_on_remove(
            self._thermostat.register_timer_update_callback(self._on_thermostat_update)
        )

        if (last_state := await self.async_get_last_number_data()) is not None:
            if last_state.native_value is not None:
                val = int(last_state.native_value)
                self._attr_native_value = float(val)
                await self._thermostat.async_set_manual_duration_minutes(val)
                return

        self._attr_native_value = float(self._thermostat.manual_duration_minutes)

    @callback
    def _on_thermostat_update(self) -> None:
        """Thermostat updated duration callback."""
        new_val = float(self._thermostat.manual_duration_minutes)
        if self._attr_native_value != new_val:
            self._attr_native_value = new_val
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Update duration value from Home Assistant."""
        val = int(value)
        self._attr_native_value = float(val)
        await self._thermostat.async_set_manual_duration_minutes(val)
        self.async_write_ha_state()
