"""Binary sensor platform for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ATTRIBUTION, ATTR_LOST_TIMESTAMP
from .tile_api import TileDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tile binary sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Add entities for all tiles
    entities = [
        TileLostBinarySensor(coordinator, tile_uuid)
        for tile_uuid in coordinator.data.keys()
    ]
    
    async_add_entities(entities)
    
    # Listen for new tiles
    @callback
    def async_check_new_tiles() -> None:
        """Check for new tiles and add them."""
        existing_uuids = set()
        for state in hass.states.async_all("binary_sensor"):
            if state.entity_id.startswith("binary_sensor.") and "_lost" in state.entity_id:
                # Extract UUID from entity
                unique_id = state.attributes.get("tile_uuid")
                if unique_id:
                    existing_uuids.add(unique_id)
        
        new_entities = [
            TileLostBinarySensor(coordinator, tile_uuid)
            for tile_uuid in coordinator.data.keys()
            if tile_uuid not in existing_uuids
        ]
        
        if new_entities:
            async_add_entities(new_entities)
    
    # Store reference for future updates
    entry.async_on_unload(
        coordinator.async_add_listener(async_check_new_tiles)
    )


class TileLostBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor indicating if a Tile is marked as lost."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "lost"

    def __init__(
        self,
        coordinator,
        tile_uuid: str,
    ) -> None:
        """Initialize the lost binary sensor."""
        super().__init__(coordinator)
        self._tile_uuid = tile_uuid
        self._attr_unique_id = f"tile_{tile_uuid}_lost"
        
        # Initial tile data
        tile = self.tile
        if tile:
            self._attr_name = "Lost"

    @property
    def tile_uuid(self) -> str:
        """Return the Tile UUID."""
        return self._tile_uuid

    @property
    def tile(self) -> TileDevice | None:
        """Return the tile device data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._tile_uuid)
        return None

    @property
    def is_on(self) -> bool | None:
        """Return True if the Tile is marked as lost."""
        if self.tile:
            return self.tile.lost
        return None

    @property
    def icon(self) -> str:
        """Return the icon."""
        if self.is_on:
            return "mdi:map-marker-question"
        return "mdi:map-marker-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {"tile_uuid": self._tile_uuid}
        
        if self.tile and self.tile.lost_timestamp:
            attrs[ATTR_LOST_TIMESTAMP] = self.tile.lost_timestamp.isoformat()
        
        return attrs

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
