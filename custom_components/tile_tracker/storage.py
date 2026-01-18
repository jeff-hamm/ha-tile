"""Persistent storage for Tile Tracker integration.

This module provides persistent storage functionality inspired by the Life360
integration's storage patterns. It allows storing Tile data (last known locations,
device details) that persists across Home Assistant restarts.

Copyright (c) 2024-2026 Jeff Hamm
SPDX-License-Identifier: MIT

Inspired by the Life360 integration:
https://github.com/home-assistant/core/tree/dev/homeassistant/components/life360
Life360 integration is licensed under Apache 2.0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping, Self

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1


@dataclass
class StoredTileLocation:
    """Stored Tile location data."""

    latitude: float
    longitude: float
    gps_accuracy: int  # meters
    last_seen: datetime
    at_loc_since: datetime | None = None
    address: str | None = None
    speed: float = 0.0  # mph
    altitude: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the data."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "gps_accuracy": self.gps_accuracy,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "at_loc_since": self.at_loc_since.isoformat() if self.at_loc_since else None,
            "address": self.address,
            "speed": self.speed,
            "altitude": self.altitude,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Initialize from a dictionary."""
        last_seen = data.get("last_seen")
        if isinstance(last_seen, str):
            last_seen = dt_util.parse_datetime(last_seen)
        
        at_loc_since = data.get("at_loc_since")
        if isinstance(at_loc_since, str):
            at_loc_since = dt_util.parse_datetime(at_loc_since)
        
        return cls(
            latitude=data["latitude"],
            longitude=data["longitude"],
            gps_accuracy=data.get("gps_accuracy", 0),
            last_seen=last_seen or dt_util.utcnow(),
            at_loc_since=at_loc_since,
            address=data.get("address"),
            speed=data.get("speed", 0.0),
            altitude=data.get("altitude"),
        )


@dataclass
class StoredTileData:
    """Stored data for a single Tile device."""

    tile_uuid: str
    name: str
    tile_type: str | None = None
    location: StoredTileLocation | None = None
    battery_level: int | None = None
    battery_charging: bool = False
    ring_state: str | None = None
    available_songs: list[dict] | None = None
    selected_song_id: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the data."""
        return {
            "tile_uuid": self.tile_uuid,
            "name": self.name,
            "tile_type": self.tile_type,
            "location": self.location.as_dict() if self.location else None,
            "battery_level": self.battery_level,
            "battery_charging": self.battery_charging,
            "ring_state": self.ring_state,
            "available_songs": self.available_songs,
            "selected_song_id": self.selected_song_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Initialize from a dictionary."""
        location = None
        if data.get("location"):
            location = StoredTileLocation.from_dict(data["location"])
        
        return cls(
            tile_uuid=data["tile_uuid"],
            name=data["name"],
            tile_type=data.get("tile_type"),
            location=location,
            battery_level=data.get("battery_level"),
            battery_charging=data.get("battery_charging", False),
            ring_state=data.get("ring_state"),
            available_songs=data.get("available_songs"),
            selected_song_id=data.get("selected_song_id", 0),
        )


@dataclass
class TileTrackerStoreData:
    """Complete storage data for Tile Tracker."""

    tiles: dict[str, StoredTileData] = field(default_factory=dict)
    last_updated: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the data."""
        return {
            "tiles": {uuid: tile.as_dict() for uuid, tile in self.tiles.items()},
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Initialize from a dictionary."""
        tiles = {}
        for uuid, tile_data in data.get("tiles", {}).items():
            tiles[uuid] = StoredTileData.from_dict(tile_data)
        
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = dt_util.parse_datetime(last_updated)
        
        return cls(tiles=tiles, last_updated=last_updated)


class TileTrackerStore:
    """Tile Tracker persistent storage.
    
    Provides storage that persists across Home Assistant restarts,
    allowing faster startup and last-known-location restoration.
    """

    _loaded: bool = False
    data: TileTrackerStoreData

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize storage."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, DOMAIN)
        self.data = TileTrackerStoreData()

    @property
    def loaded(self) -> bool:
        """Return if storage has been loaded."""
        return self._loaded

    async def load(self) -> bool:
        """Load data from storage.
        
        Returns True if data was successfully loaded, False otherwise.
        """
        try:
            store_data = await self._store.async_load()
            if store_data:
                self.data = TileTrackerStoreData.from_dict(store_data)
                self._loaded = True
                return True
        except Exception:
            pass
        
        self.data = TileTrackerStoreData()
        self._loaded = True
        return False

    async def save(self) -> None:
        """Write data to storage."""
        self.data.last_updated = dt_util.utcnow()
        await self._store.async_save(self.data.as_dict())

    async def remove(self) -> None:
        """Remove storage file."""
        await self._store.async_remove()

    def get_tile(self, tile_uuid: str) -> StoredTileData | None:
        """Get stored data for a specific Tile."""
        return self.data.tiles.get(tile_uuid)

    def set_tile(self, tile_uuid: str, tile_data: StoredTileData) -> None:
        """Set stored data for a specific Tile."""
        self.data.tiles[tile_uuid] = tile_data

    def update_tile_location(
        self,
        tile_uuid: str,
        latitude: float,
        longitude: float,
        gps_accuracy: int,
        last_seen: datetime | None = None,
        **kwargs,
    ) -> None:
        """Update location for a specific Tile."""
        if tile_uuid not in self.data.tiles:
            return
        
        tile = self.data.tiles[tile_uuid]
        
        # Determine at_loc_since - keep previous if location hasn't changed significantly
        at_loc_since = last_seen or dt_util.utcnow()
        if tile.location:
            # If within ~50 meters of previous location, keep old at_loc_since
            lat_diff = abs(tile.location.latitude - latitude)
            lon_diff = abs(tile.location.longitude - longitude)
            if lat_diff < 0.0005 and lon_diff < 0.0005:  # ~50m
                at_loc_since = tile.location.at_loc_since or at_loc_since
        
        tile.location = StoredTileLocation(
            latitude=latitude,
            longitude=longitude,
            gps_accuracy=gps_accuracy,
            last_seen=last_seen or dt_util.utcnow(),
            at_loc_since=at_loc_since,
            address=kwargs.get("address"),
            speed=kwargs.get("speed", 0.0),
            altitude=kwargs.get("altitude"),
        )
