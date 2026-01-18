"""Tile Bluetooth service for playing sounds on Tile devices.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT

This module provides the BLE interface for ring/locate operations.
Uses TileAuthenticator from tile_auth.py for the authentication protocol
and TileService from tile_service.py for caching and coordination.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .tile_auth import TileVolume
from .tile_service import get_tile_service

if TYPE_CHECKING:
    from .tile_api import TileDevice

_LOGGER = logging.getLogger(__name__)


# Re-export TileVolume for backwards compatibility
__all__ = ["TileVolume", "play_sound_on_tile", "get_tile_songs"]


async def play_sound_on_tile(
    hass: HomeAssistant,
    tile: TileDevice,
    volume: str = "medium",
    duration: int = 5,
    song_id: int | None = None,
) -> bool:
    """Play a sound on a Tile device via Bluetooth.
    
    This is the main entry point for ringing a Tile from Home Assistant.
    Delegates to TileService which handles caching and connection management.
    
    Args:
        hass: Home Assistant instance
        tile: TileDevice to ring
        volume: Volume level ("low", "medium", "high", "auto")
        duration: Ring duration in seconds (1-30)
        song_id: Optional song ID to play (uses tile.selected_song_id if None)
        
    Returns:
        True if ring was successful, False otherwise
    """
    _LOGGER.info(
        "Playing sound on Tile '%s': volume=%s, duration=%d, song=%s",
        tile.name,
        volume,
        duration,
        song_id,
    )
    
    # Use selected song from tile if not specified
    if song_id is None:
        song_id = tile.selected_song_id
    
    # Get the tile service with caching
    service = get_tile_service(hass)
    
    # Ring the tile
    return await service.ring_tile(
        tile=tile,
        volume=volume,
        duration=duration,
        song_id=song_id,
    )


async def get_tile_songs(
    hass: HomeAssistant,
    tile: TileDevice,
) -> list[dict]:
    """Get available songs from a Tile device.
    
    Note: Most Tile devices have limited song support.
    This returns cached songs from the tile or defaults.
    
    Args:
        hass: Home Assistant instance
        tile: TileDevice to query
        
    Returns:
        List of song dicts: [{"id": 0, "name": "Default"}, ...]
    """
    # Return cached if available
    if tile.available_songs:
        return tile.available_songs
    
    # Return defaults - most tiles only support a few songs
    from .const import DEFAULT_SONGS
    return DEFAULT_SONGS


async def scan_for_tiles(
    hass: HomeAssistant,
    timeout: float = 10.0,
    force_refresh: bool = False,
) -> list[dict]:
    """Scan for nearby Tile devices via Bluetooth.
    
    Args:
        hass: Home Assistant instance
        timeout: Scan timeout in seconds
        force_refresh: Force new scan even if cache is valid
        
    Returns:
        List of discovered tile info dicts with address, name, rssi
    """
    service = get_tile_service(hass)
    tiles = await service.scan_for_tiles(timeout=timeout, force_refresh=force_refresh)
    
    return [
        {
            "address": device.address,
            "name": device.name or "Unknown Tile",
            "rssi": adv_data.rssi if adv_data else -100,
        }
        for device, adv_data in tiles
    ]


def get_cache_stats(hass: HomeAssistant) -> dict:
    """Get BLE cache statistics.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        Dict with cache stats (uuid_mappings, cached_devices, etc)
    """
    service = get_tile_service(hass)
    return service.get_cache_stats()


def clear_cache(hass: HomeAssistant) -> None:
    """Clear the BLE cache.
    
    Args:
        hass: Home Assistant instance
    """
    service = get_tile_service(hass)
    service.clear_cache()
