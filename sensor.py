"""Sensor platform for Eco Thermostat."""
from __future__ import annotations

from datetime import datetime
import logging
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
    """Set up Eco Thermostat sensor entities."""
    thermostat: EcoThermostat | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if thermostat is None:
        _LOGGER.error("Thermostat not found for entry %s in sensor platform setup", entry.entry_id)
        return

    async_add_entities([
        EcoThermostatTimerEndSensor(thermostat),
        EcoThermostatHVACStateSensor(thermostat),
    ])


class EcoThermostatTimerEndSensor(SensorEntity):
    """Sensor entity indicating the end timestamp of manual heating."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def __init__(self, thermostat: EcoThermostat) -> None:
        """Initialize timer end sensor entity."""
        self._thermostat = thermostat
        base_id = slugify(thermostat.name or "eco_thermostat")
        self.entity_id = f"sensor.{base_id}_fin_temporizador"
        self._attr_unique_id = f"{thermostat.unique_id}_fin_temporizador"
        self._attr_name = "Fin Temporizador"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info matching the climate entity."""
        return self._thermostat.device_info

    @property
    def native_value(self) -> datetime | None:
        """Return the datetime when manual timer finishes."""
        return self._thermostat.manual_timer_end

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._thermostat.register_timer_update_callback(self._on_thermostat_update)
        )

    @callback
    def _on_thermostat_update(self) -> None:
        """Thermostat updated timer state callback."""
        self.async_write_ha_state()


class EcoThermostatHVACStateSensor(SensorEntity):
    """Sensor entity indicating current HVAC state (auto, manual, window-open, etc.)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat-cog"

    def __init__(self, thermostat: EcoThermostat) -> None:
        """Initialize HVAC state sensor entity."""
        self._thermostat = thermostat
        base_id = slugify(thermostat.name or "eco_thermostat")
        self.entity_id = f"sensor.{base_id}_hvac_state"
        self._attr_unique_id = f"{thermostat.unique_id}_hvac_state"
        self._attr_name = "Estat HVAC"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info matching the climate entity."""
        return self._thermostat.device_info

    @property
    def native_value(self) -> str | None:
        """Return the current HVAC state."""
        return str(self._thermostat.hvac_state) if self._thermostat.hvac_state else None

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._thermostat.register_timer_update_callback(self._on_thermostat_update)
        )

    @callback
    def _on_thermostat_update(self) -> None:
        """Thermostat updated timer/state callback."""
        self.async_write_ha_state()
