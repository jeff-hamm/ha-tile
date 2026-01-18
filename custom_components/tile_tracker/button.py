"""Button platform for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ATTRIBUTION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tile buttons based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    async_add_entities([TileRefreshButton(coordinator, entry)])


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
