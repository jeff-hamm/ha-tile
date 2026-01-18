"""Tile API client for Home Assistant.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    TILE_API_BASE,
    TILE_APP_ID,
    TILE_APP_VERSION,
    TILE_CLIENT_UUID,
    TILE_USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class TileAuthError(Exception):
    """Raised when authentication fails."""


@dataclass
class TileDevice:
    """Represents a Tile device."""

    tile_uuid: str
    name: str
    auth_key: str
    archetype: str
    firmware_version: str
    hardware_version: str | None
    product: str
    visible: bool
    is_dead: bool
    expected_tdt_cmd_config: str | None
    
    # State info
    advertised_rssi: float | None = None
    speed: float | None = None
    ring_state: str | None = None
    battery_status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    accuracy: float | None = None
    last_timestamp: datetime | None = None
    connection_state: str | None = None
    voip_state: str | None = None
    
    # Lost status (from diagnostics)
    lost: bool = False
    lost_timestamp: datetime | None = None
    
    # Device kind (TILE, PHONE, etc.)
    kind: str = "TILE"
    
    # MAC address (derived from UUID)
    mac_address: str | None = None
    
    # Song configuration (populated via BLE when available)
    available_songs: list[dict] | None = None  # [{"id": 0, "name": "Default"}, ...]
    selected_song_id: int = 0  # Currently selected song ID for ring

    @classmethod
    def from_api_response(cls, tile_uuid: str, data: dict[str, Any]) -> TileDevice:
        """Create TileDevice from API response."""
        last_state = data.get("last_tile_state", {}) or {}
        firmware = data.get("firmware", {}) or {}
        
        # Parse timestamp
        timestamp = last_state.get("timestamp")
        last_ts = None
        if timestamp:
            try:
                # Tile API returns milliseconds since epoch - use UTC timezone
                last_ts = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        
        # Parse lost timestamp
        lost_ts_raw = data.get("lost_timestamp")
        lost_ts = None
        if lost_ts_raw:
            try:
                if isinstance(lost_ts_raw, (int, float)):
                    lost_ts = datetime.fromtimestamp(lost_ts_raw / 1000, tz=timezone.utc)
                elif isinstance(lost_ts_raw, str):
                    # ISO format - ensure timezone aware
                    parsed = datetime.fromisoformat(lost_ts_raw.replace("Z", "+00:00"))
                    lost_ts = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        
        # Derive MAC address from UUID (first 12 chars = MAC without colons)
        mac_address = None
        uuid_clean = tile_uuid.replace("-", "").replace(":", "").upper()
        if len(uuid_clean) >= 12:
            mac_address = ":".join(uuid_clean[i:i+2] for i in range(0, 12, 2))

        return cls(
            tile_uuid=tile_uuid,
            name=data.get("name", "Unknown Tile"),
            auth_key=data.get("auth_key", ""),
            archetype=data.get("archetype", "UNKNOWN"),
            firmware_version=data.get("firmware_version", ""),
            hardware_version=data.get("hw_version"),
            product=data.get("product", ""),
            visible=data.get("visible", True),
            is_dead=data.get("is_dead", False),
            expected_tdt_cmd_config=firmware.get("expected_tdt_cmd_config"),
            advertised_rssi=last_state.get("advertised_rssi"),
            speed=last_state.get("speed"),
            ring_state=last_state.get("ring_state"),
            battery_status=data.get("battery_status"),
            latitude=last_state.get("latitude"),
            longitude=last_state.get("longitude"),
            altitude=last_state.get("altitude"),
            accuracy=last_state.get("h_accuracy"),
            last_timestamp=last_ts,
            connection_state=last_state.get("connection_state"),
            voip_state=last_state.get("voip_state"),
            lost=data.get("lost", False),
            lost_timestamp=lost_ts,
            kind=data.get("kind", "TILE"),
            mac_address=mac_address,
        )

    @property
    def tile_type(self) -> str:
        """Return the tile type (product/archetype)."""
        return self.product or self.archetype
    
    @property
    def last_tile_state(self) -> str | None:
        """Return last tile state as formatted string."""
        if self.last_timestamp:
            return self.last_timestamp.isoformat()
        return None


class TileApiClient:
    """Client for the Tile API."""

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the Tile API client."""
        self._email = email
        self._password = password
        self._session = session
        self._cookie: str | None = None
        self._own_session = False
        self._logged_in = False

    @property
    def is_logged_in(self) -> bool:
        """Return True if logged in."""
        return self._logged_in and self._cookie is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    def _get_headers(self, include_cookie: bool = True) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "User-Agent": TILE_USER_AGENT,
            "tile_app_id": TILE_APP_ID,
            "tile_app_version": TILE_APP_VERSION,
            "tile_client_uuid": TILE_CLIENT_UUID,
            "tile_request_timestamp": str(int(datetime.now().timestamp() * 1000)),
        }
        if include_cookie and self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    async def login(self) -> bool:
        """Login to the Tile API."""
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/clients/{TILE_CLIENT_UUID}/sessions"
        headers = self._get_headers(include_cookie=False)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        data = {
            "email": self._email,
            "password": self._password,
        }

        try:
            async with session.post(url, headers=headers, data=data) as response:
                # Get cookie from response
                cookie = response.headers.get("Set-Cookie")
                if cookie:
                    self._cookie = cookie
                
                result = await response.json()
                
                if result.get("result_code") != 0:
                    error_msg = result.get("result", {}).get("message", "Unknown error")
                    _LOGGER.error("Tile API login failed: %s", error_msg)
                    raise TileAuthError(error_msg)
                
                if result.get("result", {}).get("message") == "Invalid credentials":
                    _LOGGER.error("Tile API reported invalid credentials")
                    raise TileAuthError("Invalid credentials")
                
                _LOGGER.debug("Tile API login successful")
                self._logged_in = True
                return True

        except aiohttp.ClientError as err:
            _LOGGER.error("Error connecting to Tile API: %s", err)
            raise TileAuthError(f"Connection error: {err}") from err

    async def get_tiles(self, fetch_details: bool = True) -> list[TileDevice]:
        """Get all tiles from the account.
        
        Args:
            fetch_details: If True, fetch full details for each tile (slower but more complete)
        """
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/users/groups"
        params = {"last_modified_timestamp": "0"}
        
        try:
            async with session.get(
                url, headers=self._get_headers(), params=params
            ) as response:
                result = await response.json()
                
                if result.get("result_code") != 0:
                    error_msg = result.get("result", {}).get("message", "Unknown error")
                    _LOGGER.error("Error getting tiles: %s", error_msg)
                    return []
                
                nodes = result.get("result", {}).get("nodes", {})
                tiles = []
                tile_uuids = []
                
                for tile_uuid, tile_data in nodes.items():
                    # Skip GROUP nodes, only process actual tiles
                    if tile_data.get("node_type") == "GROUP":
                        continue
                    
                    # Filter out dead and invisible tiles
                    if tile_data.get("is_dead", False):
                        _LOGGER.debug("Skipping dead tile: %s", tile_data.get("name"))
                        continue
                    if not tile_data.get("visible", True):
                        _LOGGER.debug("Skipping invisible tile: %s", tile_data.get("name"))
                        continue
                    
                    tile_uuids.append(tile_uuid)
                    
                    if not fetch_details:
                        try:
                            tile = TileDevice.from_api_response(tile_uuid, tile_data)
                            tiles.append(tile)
                        except Exception as err:
                            _LOGGER.warning(
                                "Error parsing tile %s: %s", tile_uuid, err
                            )
                
                # Fetch full details for each tile if requested
                if fetch_details and tile_uuids:
                    for tile_uuid in tile_uuids:
                        tile = await self.get_tile(tile_uuid)
                        if tile:
                            tiles.append(tile)

                _LOGGER.debug("Found %d active tiles", len(tiles))
                return tiles

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting tiles: %s", err)
            return []

    async def get_tile(self, tile_uuid: str) -> TileDevice | None:
        """Get a specific tile by UUID."""
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        
        try:
            async with session.get(url, headers=self._get_headers()) as response:
                result = await response.json()
                
                if result.get("result_code") != 0:
                    error_msg = result.get("result", {}).get("message", "Unknown error")
                    _LOGGER.error("Error getting tile %s: %s", tile_uuid, error_msg)
                    return None
                
                tile_data = result.get("result", {})
                return TileDevice.from_api_response(tile_uuid, tile_data)

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting tile %s: %s", tile_uuid, err)
            return None

    async def get_tile_states(self) -> dict[str, dict[str, Any]]:
        """Get current states for all tiles."""
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/tiles/tile_states"
        
        try:
            async with session.get(url, headers=self._get_headers()) as response:
                result = await response.json()
                
                if result.get("result_code") != 0:
                    error_msg = result.get("result", {}).get("message", "Unknown error")
                    _LOGGER.error("Error getting tile states: %s", error_msg)
                    return {}
                
                return result.get("result", {})

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting tile states: %s", err)
            return {}

    async def set_lost(self, tile_uuid: str, lost: bool) -> bool:
        """Mark a tile as lost or found.
        
        Args:
            tile_uuid: The UUID of the tile
            lost: True to mark as lost, False to mark as found
            
        Returns:
            True if successful, False otherwise
        """
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"
        
        data = {"lost": lost}
        
        try:
            async with session.patch(url, headers=headers, json=data) as response:
                result = await response.json()
                
                if result.get("result_code") != 0:
                    error_msg = result.get("result", {}).get("message", "Unknown error")
                    _LOGGER.error("Error setting lost status for %s: %s", tile_uuid, error_msg)
                    return False
                
                _LOGGER.info("Set lost=%s for tile %s", lost, tile_uuid)
                return True

        except aiohttp.ClientError as err:
            _LOGGER.error("Error setting lost status for %s: %s", tile_uuid, err)
            return False

    async def get_tile_raw(self, tile_uuid: str) -> dict[str, Any] | None:
        """Get raw API response for a tile (for diagnostics).
        
        Args:
            tile_uuid: The UUID of the tile
            
        Returns:
            Raw API response dict or None
        """
        session = await self._get_session()
        
        url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        
        try:
            async with session.get(url, headers=self._get_headers()) as response:
                result = await response.json()
                
                if result.get("result_code") != 0:
                    return None
                
                return result.get("result", {})

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting raw tile data %s: %s", tile_uuid, err)
            return None

    async def get_all_tiles_raw(self) -> list[dict[str, Any]]:
        """Get raw API response for all tiles (for diagnostics).
        
        Similar to the official Tile app's diagnostics download.
        
        Returns:
            List of raw tile data dicts
        """
        tiles = await self.get_tiles(fetch_details=False)
        raw_tiles = []
        
        for tile in tiles:
            raw = await self.get_tile_raw(tile.tile_uuid)
            if raw:
                # Format similar to official diagnostics
                diag = {
                    "uuid": tile.tile_uuid,
                    "name": tile.name,
                    "archetype": tile.archetype,
                    "kind": tile.kind,
                    "firmware_version": tile.firmware_version,
                    "hardware_version": tile.hardware_version,
                    "latitude": tile.latitude,
                    "longitude": tile.longitude,
                    "altitude": tile.altitude,
                    "accuracy": tile.accuracy,
                    "last_timestamp": tile.last_timestamp.isoformat() if tile.last_timestamp else None,
                    "ring_state": tile.ring_state,
                    "voip_state": tile.voip_state,
                    "lost": tile.lost,
                    "lost_timestamp": tile.lost_timestamp.isoformat() if tile.lost_timestamp else None,
                    "dead": tile.is_dead,
                    "visible": tile.visible,
                }
                raw_tiles.append(diag)
        
        return raw_tiles

    async def close(self) -> None:
        """Close the session if we own it."""
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
