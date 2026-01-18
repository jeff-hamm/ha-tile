"""Location filtering for Tile Tracker integration.

This module provides location filtering functionality inspired by the Life360
integration. It filters out location updates with poor GPS accuracy or stale
timestamps to improve tracking quality.

Copyright (c) 2024-2026 Jeff Hamm
SPDX-License-Identifier: MIT

Inspired by the Life360 integration:
https://github.com/home-assistant/core/tree/dev/homeassistant/components/life360
Life360 integration is licensed under Apache 2.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
import logging
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class FilterReason(IntEnum):
    """Reason why a location update was filtered."""

    ACCEPTED = 0
    STALE_TIMESTAMP = 1
    POOR_ACCURACY = 2
    INVALID_COORDS = 3
    NO_CHANGE = 4


@dataclass
class LocationUpdate:
    """A location update to be filtered."""

    latitude: float
    longitude: float
    gps_accuracy: int  # meters
    timestamp: datetime
    speed: float = 0.0
    altitude: float | None = None
    address: str | None = None

    def is_valid(self) -> bool:
        """Check if coordinates are valid."""
        return (
            -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
            and self.gps_accuracy >= 0
        )


@dataclass
class FilterResult:
    """Result of location filtering."""

    accepted: bool
    reason: FilterReason
    message: str | None = None


@dataclass
class LocationFilterConfig:
    """Configuration for location filtering."""

    max_gps_accuracy: int | None = None  # meters, None = no limit
    reject_stale: bool = True  # Reject updates older than previous
    min_distance_meters: float = 0  # Minimum distance to count as movement
    driving_speed_threshold: float | None = None  # mph, speeds above = driving


class LocationFilter:
    """Filter location updates based on configurable criteria.
    
    Inspired by Life360's approach to filtering bad location data.
    """

    def __init__(self, config: LocationFilterConfig | None = None) -> None:
        """Initialize the location filter."""
        self.config = config or LocationFilterConfig()
        self._last_accepted: dict[str, LocationUpdate] = {}
        self._ignored_reasons: dict[str, list[str]] = {}

    def filter(
        self,
        entity_id: str,
        update: LocationUpdate,
    ) -> FilterResult:
        """Filter a location update.
        
        Args:
            entity_id: Unique identifier for the entity
            update: The location update to filter
            
        Returns:
            FilterResult indicating if the update was accepted
        """
        # Check for valid coordinates
        if not update.is_valid():
            return FilterResult(
                accepted=False,
                reason=FilterReason.INVALID_COORDS,
                message=f"Invalid coordinates: ({update.latitude}, {update.longitude})",
            )

        # Check GPS accuracy
        if (
            self.config.max_gps_accuracy is not None
            and update.gps_accuracy > self.config.max_gps_accuracy
        ):
            self._add_ignored_reason(entity_id, "gps_accuracy")
            return FilterResult(
                accepted=False,
                reason=FilterReason.POOR_ACCURACY,
                message=f"GPS accuracy {update.gps_accuracy}m exceeds limit {self.config.max_gps_accuracy}m",
            )

        # Check for stale timestamp
        last = self._last_accepted.get(entity_id)
        if last and self.config.reject_stale:
            if update.timestamp < last.timestamp:
                self._add_ignored_reason(entity_id, "last_seen")
                return FilterResult(
                    accepted=False,
                    reason=FilterReason.STALE_TIMESTAMP,
                    message=f"Update timestamp {update.timestamp} is older than last accepted {last.timestamp}",
                )

        # Check for minimum movement
        if last and self.config.min_distance_meters > 0:
            distance = self._haversine_distance(
                last.latitude, last.longitude,
                update.latitude, update.longitude,
            )
            if distance < self.config.min_distance_meters:
                return FilterResult(
                    accepted=False,
                    reason=FilterReason.NO_CHANGE,
                    message=f"Movement {distance:.1f}m is less than minimum {self.config.min_distance_meters}m",
                )

        # Update accepted
        self._last_accepted[entity_id] = update
        self._clear_ignored_reasons(entity_id)
        
        return FilterResult(accepted=True, reason=FilterReason.ACCEPTED)

    def is_driving(self, update: LocationUpdate) -> bool:
        """Determine if the speed indicates driving."""
        if self.config.driving_speed_threshold is None:
            return False
        return update.speed >= self.config.driving_speed_threshold

    def get_ignored_reasons(self, entity_id: str) -> list[str]:
        """Get list of reasons why recent updates were ignored."""
        return self._ignored_reasons.get(entity_id, [])

    def get_last_accepted(self, entity_id: str) -> LocationUpdate | None:
        """Get the last accepted location for an entity."""
        return self._last_accepted.get(entity_id)

    def clear(self, entity_id: str | None = None) -> None:
        """Clear filter state for an entity or all entities."""
        if entity_id:
            self._last_accepted.pop(entity_id, None)
            self._ignored_reasons.pop(entity_id, None)
        else:
            self._last_accepted.clear()
            self._ignored_reasons.clear()

    def _add_ignored_reason(self, entity_id: str, reason: str) -> None:
        """Add an ignored reason for an entity."""
        if entity_id not in self._ignored_reasons:
            self._ignored_reasons[entity_id] = []
        if reason not in self._ignored_reasons[entity_id]:
            self._ignored_reasons[entity_id].append(reason)

    def _clear_ignored_reasons(self, entity_id: str) -> None:
        """Clear ignored reasons when an update is accepted."""
        self._ignored_reasons.pop(entity_id, None)

    @staticmethod
    def _haversine_distance(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Calculate distance between two points in meters using Haversine formula."""
        from math import radians, sin, cos, sqrt, atan2

        R = 6371000  # Earth radius in meters

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return R * c
