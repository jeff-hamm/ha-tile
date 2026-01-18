"""Button platform for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ATTRIBUTION
from .tile_api import TileDevice
from .tile_service import get_tile_service

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tile buttons based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    entities = []
    
    # Add global refresh button
    entities.append(TileRefreshButton(coordinator, entry))
    
    # Add per-device buttons
    for tile_uuid in coordinator.data.keys():
        entities.extend([
            TileLocateButton(hass, coordinator, tile_uuid),
            TileRefreshDeviceButton(coordinator, tile_uuid),
            TileScanButton(hass, coordinator, tile_uuid),
        ])
    
    async_add_entities(entities)
    
    # Listen for new tiles
    @callback
    def async_check_new_tiles() -> None:
        """Check for new tiles and add them."""
        existing_uuids = set()
        for state in hass.states.async_all("button"):
            if "_locate" in state.entity_id:
                unique_id = state.attributes.get("tile_uuid")
                if unique_id:
                    existing_uuids.add(unique_id)
        
        new_entities = []
        for tile_uuid in coordinator.data.keys():
            if tile_uuid not in existing_uuids:
                new_entities.extend([
                    TileLocateButton(hass, coordinator, tile_uuid),
                    TileRefreshDeviceButton(coordinator, tile_uuid),
                    TileScanButton(hass, coordinator, tile_uuid),
                ])
        
        if new_entities:
            async_add_entities(new_entities)
    
    entry.async_on_unload(
        coordinator.async_add_listener(async_check_new_tiles)
    )


class TileRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh all Tile devices."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_name = "Refresh Tiles"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"tile_refresh_{entry.entry_id}"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Tile Tracker",
            "manufacturer": "Tile",
            "model": "Tile Account",
            "entry_type": "service",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.debug("Refresh Tiles button pressed")
        await self.coordinator.async_request_refresh()


class TileLocateButton(CoordinatorEntity, ButtonEntity):
    """Button to ring/locate a specific Tile."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-ring"
    _attr_translation_key = "locate"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        tile_uuid: str,
    ) -> None:
        """Initialize the locate button."""
        super().__init__(coordinator)
        self._hass = hass
        self._tile_uuid = tile_uuid
        self._attr_unique_id = f"tile_{tile_uuid}_locate"
        self._attr_name = "Locate"

    @property
    def tile(self) -> TileDevice | None:
        """Return the tile device data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._tile_uuid)
        return None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"tile_uuid": self._tile_uuid}

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
        tile = self.tile
        return (
            self.coordinator.last_update_success
            and tile is not None
            and bool(tile.auth_key)
        )

    async def async_press(self) -> None:
        """Handle the button press - ring the Tile."""
        tile = self.tile
        if not tile:
            _LOGGER.error("Tile not found: %s", self._tile_uuid)
            return
        
        _LOGGER.info("Locating Tile: %s", tile.name)
        
        tile_service = get_tile_service(self._hass)
        success = await tile_service.ring_tile(tile=tile)
        
        if not success:
            _LOGGER.warning("Failed to ring Tile %s", tile.name)


class TileRefreshDeviceButton(CoordinatorEntity, ButtonEntity):
    """Button to refresh a specific Tile's data."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"
    _attr_translation_key = "refresh"

    def __init__(
        self,
        coordinator,
        tile_uuid: str,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._tile_uuid = tile_uuid
        self._attr_unique_id = f"tile_{tile_uuid}_refresh"
        self._attr_name = "Refresh"

    @property
    def tile(self) -> TileDevice | None:
        """Return the tile device data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._tile_uuid)
        return None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"tile_uuid": self._tile_uuid}

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

    async def async_press(self) -> None:
        """Handle the button press - refresh tile data."""
        _LOGGER.debug("Refreshing Tile: %s", self._tile_uuid)
        await self.coordinator.async_request_refresh()


class TileScanButton(CoordinatorEntity, ButtonEntity):
    """Button to scan for a specific Tile via BLE."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:bluetooth-audio"
    _attr_translation_key = "scan"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        tile_uuid: str,
    ) -> None:
        """Initialize the scan button."""
        super().__init__(coordinator)
        self._hass = hass
        self._tile_uuid = tile_uuid
        self._attr_unique_id = f"tile_{tile_uuid}_scan"
        self._attr_name = "Scan"

    @property
    def tile(self) -> TileDevice | None:
        """Return the tile device data."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._tile_uuid)
        return None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"tile_uuid": self._tile_uuid}

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

    async def async_press(self) -> None:
        """Handle the button press - scan for the Tile."""
        tile = self.tile
        if not tile:
            _LOGGER.error("Tile not found: %s", self._tile_uuid)
            return
        
        _LOGGER.info("Scanning for Tile: %s", tile.name)
        
        tile_service = get_tile_service(self._hass)
        device = await tile_service.find_tile_ble(
            tile_uuid=self._tile_uuid,
            force_scan=True,
        )
        
        if device:
            _LOGGER.info("Found Tile %s at %s", tile.name, device.address)
        else:
            _LOGGER.warning("Tile %s not found nearby", tile.name)
