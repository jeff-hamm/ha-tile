"""Switch platform for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
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
    """Set up Tile switches based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    
    # Add entities for all tiles
    entities = [
        TileLostSwitch(coordinator, api, tile_uuid)
        for tile_uuid in coordinator.data.keys()
    ]
    
    async_add_entities(entities)
    
    # Listen for new tiles
    @callback
    def async_check_new_tiles() -> None:
        """Check for new tiles and add them."""
        existing_uuids = set()
        for state in hass.states.async_all("switch"):
            if "_lost" in state.entity_id:
                unique_id = state.attributes.get("tile_uuid")
                if unique_id:
                    existing_uuids.add(unique_id)
        
        new_entities = [
            TileLostSwitch(coordinator, api, tile_uuid)
            for tile_uuid in coordinator.data.keys()
            if tile_uuid not in existing_uuids
        ]
        
        if new_entities:
            async_add_entities(new_entities)
    
    entry.async_on_unload(
        coordinator.async_add_listener(async_check_new_tiles)
    )


class TileLostSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to mark a Tile as lost or found."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_translation_key = "lost"

    def __init__(
        self,
        coordinator,
        api,
        tile_uuid: str,
    ) -> None:
        """Initialize the lost switch."""
        super().__init__(coordinator)
        self._api = api
        self._tile_uuid = tile_uuid
        self._attr_unique_id = f"tile_{tile_uuid}_lost"
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mark the Tile as lost."""
        _LOGGER.info("Marking Tile %s as lost", self._tile_uuid)
        success = await self._api.set_lost(self._tile_uuid, True)
        if success:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Mark the Tile as found."""
        _LOGGER.info("Marking Tile %s as found", self._tile_uuid)
        success = await self._api.set_lost(self._tile_uuid, False)
        if success:
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
