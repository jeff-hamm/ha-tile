"""Select platform for Tile Tracker integration.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    ATTR_AVAILABLE_SONGS,
    ATTR_SELECTED_SONG,
    DEFAULT_SONGS,
    DOMAIN,
)
from .tile_api import TileDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tile Tracker select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    entities = []
    for tile in coordinator.data.values():
        entities.append(TileSongSelect(coordinator, tile))
    
    async_add_entities(entities)


class TileSongSelect(CoordinatorEntity, SelectEntity):
    """Select entity for choosing which song a Tile plays."""

    _attr_has_entity_name = True
    _attr_translation_key = "song"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        tile: TileDevice,
    ) -> None:
        """Initialize the song select entity."""
        super().__init__(coordinator)
        self._tile = tile
        self._attr_unique_id = f"{tile.tile_uuid}_song"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, tile.tile_uuid)},
            "name": tile.name,
            "manufacturer": "Tile",
            "model": tile.tile_type or "Unknown",
        }
        # Initialize with default songs
        self._songs = tile.available_songs or DEFAULT_SONGS

    @property
    def current_option(self) -> str | None:
        """Return the current selected song."""
        song_id = self._tile.selected_song_id
        for song in self._songs:
            if song["id"] == song_id:
                return song["name"]
        # Return first song if not found
        return self._songs[0]["name"] if self._songs else None

    @property
    def options(self) -> list[str]:
        """Return the list of available songs."""
        # Update songs from tile if available
        if self._tile.available_songs:
            self._songs = self._tile.available_songs
        return [song["name"] for song in self._songs]

    async def async_select_option(self, option: str) -> None:
        """Select a song option."""
        for song in self._songs:
            if song["name"] == option:
                self._tile.selected_song_id = song["id"]
                _LOGGER.debug(
                    "Selected song '%s' (id=%d) for Tile %s",
                    option,
                    song["id"],
                    self._tile.name,
                )
                self.async_write_ha_state()
                return
        
        _LOGGER.warning("Song '%s' not found in available songs", option)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_AVAILABLE_SONGS: self._songs,
            ATTR_SELECTED_SONG: self._tile.selected_song_id,
            "tile_uuid": self._tile.tile_uuid,
        }

    async def async_update_songs(self) -> None:
        """Update the list of available songs from the Tile."""
        from .tile_bluetooth import get_tile_songs
        
        try:
            songs = await get_tile_songs(self.hass, self._tile)
            if songs:
                self._songs = songs
                self._tile.available_songs = songs
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.debug("Could not update songs for %s: %s", self._tile.name, err)
