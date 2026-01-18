"""Diagnostics support for Tile Tracker.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Keys to redact from diagnostics
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "auth_key",
    "latitude",
    "longitude",
    "altitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.get("coordinator")
    api = data.get("api")
    
    tiles_data = []
    
    if coordinator and coordinator.data:
        for tile in coordinator.data.values():
            tile_diag = {
                "uuid": tile.tile_uuid,
                "name": tile.name,
                "archetype": tile.archetype,
                "kind": tile.kind,
                "product": tile.product,
                "firmware_version": tile.firmware_version,
                "hardware_version": tile.hardware_version,
                "mac_address": tile.mac_address,
                "latitude": tile.latitude,
                "longitude": tile.longitude,
                "altitude": tile.altitude,
                "accuracy": tile.accuracy,
                "last_timestamp": tile.last_timestamp.isoformat() if tile.last_timestamp else None,
                "ring_state": tile.ring_state,
                "voip_state": tile.voip_state,
                "connection_state": tile.connection_state,
                "lost": tile.lost,
                "lost_timestamp": tile.lost_timestamp.isoformat() if tile.lost_timestamp else None,
                "dead": tile.is_dead,
                "visible": tile.visible,
                "battery_status": tile.battery_status,
                "advertised_rssi": tile.advertised_rssi,
                "speed": tile.speed,
            }
            tiles_data.append(tile_diag)
    
    diagnostics = {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "tiles": [
            async_redact_data(tile, TO_REDACT) for tile in tiles_data
        ],
        "coordinator": {
            "last_update_success": coordinator.last_update_success if coordinator else None,
            "last_update_time": coordinator.last_update_success_time.isoformat() if coordinator and coordinator.last_update_success_time else None,
            "update_interval": str(coordinator.update_interval) if coordinator else None,
        },
    }
    
    return diagnostics


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device
) -> dict[str, Any]:
    """Return diagnostics for a specific device."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.get("coordinator")
    
    # Find the tile for this device
    tile_uuid = None
    for identifier in device.identifiers:
        if identifier[0] == DOMAIN:
            tile_uuid = identifier[1]
            break
    
    if not tile_uuid or not coordinator or not coordinator.data:
        return {"error": "Tile not found"}
    
    tile = coordinator.data.get(tile_uuid)
    if not tile:
        return {"error": f"Tile {tile_uuid} not found in coordinator data"}
    
    # Return detailed diagnostics for this specific tile
    tile_diag = {
        "uuid": tile.tile_uuid,
        "name": tile.name,
        "archetype": tile.archetype,
        "kind": tile.kind,
        "product": tile.product,
        "firmware_version": tile.firmware_version,
        "hardware_version": tile.hardware_version,
        "mac_address": tile.mac_address,
        "latitude": tile.latitude,
        "longitude": tile.longitude,
        "altitude": tile.altitude,
        "accuracy": tile.accuracy,
        "last_timestamp": tile.last_timestamp.isoformat() if tile.last_timestamp else None,
        "ring_state": tile.ring_state,
        "voip_state": tile.voip_state,
        "connection_state": tile.connection_state,
        "lost": tile.lost,
        "lost_timestamp": tile.lost_timestamp.isoformat() if tile.lost_timestamp else None,
        "dead": tile.is_dead,
        "visible": tile.visible,
        "battery_status": tile.battery_status,
        "advertised_rssi": tile.advertised_rssi,
        "speed": tile.speed,
        "available_songs": tile.available_songs,
        "selected_song_id": tile.selected_song_id,
    }
    
    return async_redact_data(tile_diag, TO_REDACT)
