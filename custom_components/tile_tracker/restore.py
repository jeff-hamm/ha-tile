"""State restoration for Tile Tracker integration.

This module provides state restoration functionality inspired by the Life360
integration. It allows Tile device_tracker entities to restore their last
known state when Home Assistant restarts.

Copyright (c) 2024-2026 Jeff Hamm
SPDX-License-Identifier: MIT

Inspired by the Life360 integration:
https://github.com/home-assistant/core/tree/dev/homeassistant/components/life360
Life360 integration is licensed under Apache 2.0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Self

from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util


@dataclass
class TileRestoreData(ExtraStoredData):
    """Extra stored data for Tile device tracker restoration.
    
    This class stores location and state data that can be restored
    after Home Assistant restarts, allowing Tiles to show their
    last known location immediately.
    """

    # Location data
    latitude: float | None = None
    longitude: float | None = None
    gps_accuracy: int | None = None
    last_seen: datetime | None = None
    at_loc_since: datetime | None = None
    
    # Extended attributes
    address: str | None = None
    speed: float = 0.0
    altitude: float | None = None
    
    # State data
    battery_level: int | None = None
    battery_charging: bool = False
    ring_state: str | None = None
    
    # Tile metadata
    tile_uuid: str | None = None
    tile_type: str | None = None
    
    # Song selection
    available_songs: list[dict] | None = None
    selected_song_id: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the data."""
        data = asdict(self)
        # Convert datetime to ISO format for storage
        if self.last_seen:
            data["last_seen"] = self.last_seen.isoformat()
        if self.at_loc_since:
            data["at_loc_since"] = self.at_loc_since.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Initialize from a dictionary.
        
        Args:
            data: Dictionary containing restoration data
            
        Returns:
            TileRestoreData instance
            
        Raises:
            KeyError: If required data is missing
            ValueError: If data is malformed
        """
        # Parse datetime fields
        last_seen = data.get("last_seen")
        if isinstance(last_seen, str):
            last_seen = dt_util.parse_datetime(last_seen)
        elif not isinstance(last_seen, datetime) and last_seen is not None:
            last_seen = None
            
        at_loc_since = data.get("at_loc_since")
        if isinstance(at_loc_since, str):
            at_loc_since = dt_util.parse_datetime(at_loc_since)
        elif not isinstance(at_loc_since, datetime) and at_loc_since is not None:
            at_loc_since = None

        return cls(
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            gps_accuracy=data.get("gps_accuracy"),
            last_seen=last_seen,
            at_loc_since=at_loc_since,
            address=data.get("address"),
            speed=data.get("speed", 0.0),
            altitude=data.get("altitude"),
            battery_level=data.get("battery_level"),
            battery_charging=data.get("battery_charging", False),
            ring_state=data.get("ring_state"),
            tile_uuid=data.get("tile_uuid"),
            tile_type=data.get("tile_type"),
            available_songs=data.get("available_songs"),
            selected_song_id=data.get("selected_song_id", 0),
        )

    @property
    def has_location(self) -> bool:
        """Return True if location data is available."""
        return self.latitude is not None and self.longitude is not None

    def update_from_api(
        self,
        latitude: float,
        longitude: float,
        last_seen: datetime,
        gps_accuracy: int = 0,
        **kwargs,
    ) -> None:
        """Update restoration data from API response.
        
        Args:
            latitude: New latitude
            longitude: New longitude
            last_seen: Timestamp of the update
            gps_accuracy: GPS accuracy in meters
            **kwargs: Additional attributes to update
        """
        # Determine if location has changed significantly
        location_changed = True
        if self.latitude is not None and self.longitude is not None:
            lat_diff = abs(self.latitude - latitude)
            lon_diff = abs(self.longitude - longitude)
            location_changed = lat_diff > 0.0005 or lon_diff > 0.0005  # ~50m
        
        self.latitude = latitude
        self.longitude = longitude
        self.gps_accuracy = gps_accuracy
        self.last_seen = last_seen
        
        # Only update at_loc_since if location changed significantly
        if location_changed:
            self.at_loc_since = last_seen
        elif self.at_loc_since is None:
            self.at_loc_since = last_seen
        
        # Update optional fields
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
