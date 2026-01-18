"""Sensor platform for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    ATTR_TILE_UUID,
    ATTR_FIRMWARE_VERSION,
    ATTR_HARDWARE_VERSION,
    ATTR_ACCURACY,
    ATTR_ALTITUDE,
    ATTR_SPEED,
    ATTR_VOIP_STATE,
    ATTR_KIND,
    ATTR_ARCHETYPE,
    ATTR_PRODUCT,
    ATTR_MAC_ADDRESS,
    ATTR_LAST_TIMESTAMP,
)
from .tile_api import TileDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tile sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    entities = []
    
    for tile_uuid in coordinator.data.keys():
        # RSSI sensor (disabled by default)
        entities.append(TileRssiSensor(coordinator, tile_uuid))
        # Last seen sensor
        entities.append(TileLastSeenSensor(coordinator, tile_uuid))
        # Accuracy sensor (disabled by default)
        entities.append(TileAccuracySensor(coordinator, tile_uuid))
    
    async_add_entities(entities)
    
    # Listen for new tiles
    @callback
    def async_check_new_tiles() -> None:
        """Check for new tiles and add them."""
        existing_uuids = set()
        for state in hass.states.async_all("sensor"):
            if "_rssi" in state.entity_id or "_last_seen" in state.entity_id:
                unique_id = state.attributes.get(ATTR_TILE_UUID)
                if unique_id:
                    existing_uuids.add(unique_id)
        
        new_entities = []
        for tile_uuid in coordinator.data.keys():
            if tile_uuid not in existing_uuids:
                new_entities.extend([
                    TileRssiSensor(coordinator, tile_uuid),
                    TileLastSeenSensor(coordinator, tile_uuid),
                    TileAccuracySensor(coordinator, tile_uuid),
                ])
        
        if new_entities:
            async_add_entities(new_entities)
    
    entry.async_on_unload(
        coordinator.async_add_listener(async_check_new_tiles)
    )


class TileBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Tile sensors."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        tile_uuid: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._tile_uuid = tile_uuid

    @property
    def tile(self) -> TileDevice | None:
        """Return the tile device data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._tile_uuid)
        return None

    @property
    def device_info(self):
        """Return device info."""
        if not self.tile:
            return None
        return {
            "identifiers": {(DOMAIN, self.tile.tile_uuid)},
            "name": self.tile.name,
            "manufacturer": "Tile",
            "model": self.tile.tile_type or "Tile Tracker",
            "sw_version": self.tile.firmware_version,
            "hw_version": self.tile.hardware_version,
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.tile is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TileRssiSensor(TileBaseSensor):
    """Sensor for Tile RSSI (signal strength)."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # Disabled by default
    _attr_translation_key = "rssi"

    def __init__(self, coordinator, tile_uuid: str) -> None:
        """Initialize the RSSI sensor."""
        super().__init__(coordinator, tile_uuid)
        self._attr_unique_id = f"tile_{tile_uuid}_rssi"
        self._attr_name = "Signal Strength"
        self._attr_icon = "mdi:signal"

    @property
    def native_value(self) -> float | None:
        """Return the RSSI value."""
        if self.tile:
            return self.tile.advertised_rssi
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {ATTR_TILE_UUID: self._tile_uuid}
        
        if self.tile:
            if self.tile.firmware_version:
                attrs[ATTR_FIRMWARE_VERSION] = self.tile.firmware_version
            if self.tile.hardware_version:
                attrs[ATTR_HARDWARE_VERSION] = self.tile.hardware_version
            if self.tile.mac_address:
                attrs[ATTR_MAC_ADDRESS] = self.tile.mac_address
            if self.tile.speed is not None:
                attrs[ATTR_SPEED] = self.tile.speed
            if self.tile.voip_state:
                attrs[ATTR_VOIP_STATE] = self.tile.voip_state
            if self.tile.kind:
                attrs[ATTR_KIND] = self.tile.kind
            if self.tile.archetype:
                attrs[ATTR_ARCHETYPE] = self.tile.archetype
            if self.tile.product:
                attrs[ATTR_PRODUCT] = self.tile.product
        
        return attrs


class TileLastSeenSensor(TileBaseSensor):
    """Sensor for Tile last seen timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_seen"

    def __init__(self, coordinator, tile_uuid: str) -> None:
        """Initialize the last seen sensor."""
        super().__init__(coordinator, tile_uuid)
        self._attr_unique_id = f"tile_{tile_uuid}_last_seen"
        self._attr_name = "Last Seen"
        self._attr_icon = "mdi:clock-outline"

    @property
    def native_value(self):
        """Return the last seen timestamp."""
        if self.tile and self.tile.last_timestamp:
            return self.tile.last_timestamp
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {ATTR_TILE_UUID: self._tile_uuid}


class TileAccuracySensor(TileBaseSensor):
    """Sensor for Tile location accuracy."""

    _attr_native_unit_of_measurement = "m"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False  # Disabled by default
    _attr_translation_key = "accuracy"

    def __init__(self, coordinator, tile_uuid: str) -> None:
        """Initialize the accuracy sensor."""
        super().__init__(coordinator, tile_uuid)
        self._attr_unique_id = f"tile_{tile_uuid}_accuracy"
        self._attr_name = "Location Accuracy"
        self._attr_icon = "mdi:crosshairs-gps"

    @property
    def native_value(self) -> float | None:
        """Return the accuracy value in meters."""
        if self.tile:
            return self.tile.accuracy
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {ATTR_TILE_UUID: self._tile_uuid}
        
        if self.tile:
            if self.tile.altitude is not None:
                attrs[ATTR_ALTITUDE] = self.tile.altitude
        
        return attrs
