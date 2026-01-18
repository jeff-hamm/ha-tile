"""Tile Service Layer with Caching.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT

Provides a unified service layer for Tile operations:
- API access with caching
- BLE scanning with UUID→MAC caching
- Authentication with session caching
- Ring/locate operations

The caching strategy:
- Tile list from API: Cached during coordinator updates
- UUID→MAC mapping: Cached on first scan, refreshed on cache miss
- Auth sessions: Short-lived (BLE connection), no persistent caching
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .const import (
    DOMAIN,
    FEED_SERVICE_UUID,
    UUID_MAC_CACHE_TTL,
    SCAN_CACHE_TTL,
    BLE_CONNECTION_TIMEOUT,
    BLE_AUTH_TIMEOUT,
)
from .tile_auth import (
    TileAuthenticator,
    TileVolume,
    connect_and_authenticate,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .tile_api import TileDevice

_LOGGER = logging.getLogger(__name__)


@dataclass
class CachedBleDevice:
    """Cached BLE device info."""
    address: str
    rssi: int
    last_seen: float = field(default_factory=time.time)
    device: BLEDevice | None = None
    adv_data: AdvertisementData | None = None


@dataclass
class TileBleCache:
    """Cache for UUID→MAC mappings and scan results."""
    
    # UUID to MAC address mapping (tile_uuid -> mac_address)
    uuid_to_mac: dict[str, str] = field(default_factory=dict)
    
    # MAC to cached device info
    mac_to_device: dict[str, CachedBleDevice] = field(default_factory=dict)
    
    # Last full scan timestamp
    last_scan: float = 0.0
    
    # All discovered Tiles from last scan
    discovered_tiles: list[tuple[BLEDevice, AdvertisementData]] = field(default_factory=list)
    
    def get_mac_for_uuid(self, tile_uuid: str) -> str | None:
        """Get cached MAC for a tile UUID."""
        return self.uuid_to_mac.get(tile_uuid)
    
    def get_device(self, mac_address: str) -> BLEDevice | None:
        """Get cached BLE device for MAC, if still valid."""
        cached = self.mac_to_device.get(mac_address)
        if cached and (time.time() - cached.last_seen) < SCAN_CACHE_TTL:
            return cached.device
        return None
    
    def cache_mapping(self, tile_uuid: str, mac_address: str) -> None:
        """Cache a UUID→MAC mapping."""
        self.uuid_to_mac[tile_uuid] = mac_address
        _LOGGER.debug("Cached mapping: %s -> %s", tile_uuid[:8], mac_address)
    
    def cache_device(self, device: BLEDevice, adv_data: AdvertisementData | None, rssi: int = -100) -> None:
        """Cache a discovered device."""
        self.mac_to_device[device.address] = CachedBleDevice(
            address=device.address,
            rssi=rssi,
            last_seen=time.time(),
            device=device,
            adv_data=adv_data,
        )
    
    def is_scan_stale(self) -> bool:
        """Check if we need a fresh scan."""
        return (time.time() - self.last_scan) > SCAN_CACHE_TTL
    
    def clear_scan_cache(self) -> None:
        """Clear scan cache but keep UUID→MAC mappings."""
        self.mac_to_device.clear()
        self.discovered_tiles.clear()
        self.last_scan = 0.0


class TileService:
    """Tile service layer with caching.
    
    Provides all Tile operations with intelligent caching:
    - API operations (delegated to coordinator)
    - BLE scanning with caching
    - Ring/locate with automatic connection management
    """
    
    def __init__(self, hass: HomeAssistant):
        """Initialize Tile service."""
        self.hass = hass
        self.cache = TileBleCache()
        self._scan_lock = asyncio.Lock()
    
    def get_tile_from_coordinator(self, tile_id: str) -> TileDevice | None:
        """Get a tile from coordinator cache.
        
        Args:
            tile_id: Tile UUID or name
            
        Returns:
            TileDevice if found, None otherwise
        """
        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            coordinator = data.get("coordinator")
            if coordinator and coordinator.data:
                for tile in coordinator.data.values():
                    if tile.tile_uuid == tile_id or tile.name == tile_id:
                        return tile
        return None
    
    def get_all_tiles(self) -> list:
        """Get all tiles from all coordinators."""
        tiles = []
        for entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if not isinstance(data, dict):
                continue
            coordinator = data.get("coordinator")
            if coordinator and coordinator.data:
                tiles.extend(coordinator.data.values())
        return tiles
    
    async def scan_for_tiles(
        self,
        timeout: float = 10.0,
        force_refresh: bool = False
    ) -> list[tuple[BLEDevice, AdvertisementData | None]]:
        """Scan for nearby Tile devices.
        
        Uses cache if available and not stale.
        
        Args:
            timeout: Scan timeout in seconds
            force_refresh: Force a new scan even if cache is fresh
            
        Returns:
            List of (BLEDevice, AdvertisementData) tuples
        """
        async with self._scan_lock:
            # Return cache if still valid
            if not force_refresh and not self.cache.is_scan_stale() and self.cache.discovered_tiles:
                _LOGGER.debug("Using cached scan results (%d tiles)", len(self.cache.discovered_tiles))
                return self.cache.discovered_tiles
            
            _LOGGER.debug("Starting BLE scan for Tiles (timeout=%ss)", timeout)
            
            tiles: list[tuple[BLEDevice, AdvertisementData]] = []
            seen_addresses: set[str] = set()
            
            def detection_callback(device: BLEDevice, adv_data: AdvertisementData):
                if device.address in seen_addresses:
                    return
                
                # Check for Tile services
                service_uuids = [str(u).lower() for u in (adv_data.service_uuids or [])]
                service_data_keys = [str(k).lower() for k in (adv_data.service_data or {}).keys()]
                all_services = service_uuids + service_data_keys
                
                is_tile = any(
                    "feed" in s or "feec" in s or
                    FEED_SERVICE_UUID.lower() in s or
                    "0000feed" in s or "0000feec" in s
                    for s in all_services
                )
                
                # Also check device name
                if device.name and device.name.lower() == "tile":
                    is_tile = True
                
                if is_tile:
                    seen_addresses.add(device.address)
                    tiles.append((device, adv_data))
                    self.cache.cache_device(device, adv_data, adv_data.rssi)
                    _LOGGER.debug("Found Tile: %s @ %s (RSSI: %d)",
                                 device.name or "Unknown", device.address, adv_data.rssi)
            
            try:
                scanner = BleakScanner(detection_callback=detection_callback)
                await scanner.start()
                await asyncio.sleep(timeout)
                await scanner.stop()
                
                # Also check already discovered devices
                discovered = await BleakScanner.discover(timeout=1.0)
                for device in discovered:
                    if device.address in seen_addresses:
                        continue
                    if device.name and device.name.lower() == "tile":
                        tiles.append((device, None))
                        self.cache.cache_device(device, None, -100)
                
                # Update cache
                self.cache.discovered_tiles = tiles
                self.cache.last_scan = time.time()
                
                _LOGGER.info("BLE scan complete: found %d Tile(s)", len(tiles))
                return tiles
                
            except Exception as e:
                _LOGGER.error("BLE scan failed: %s", e)
                return []
    
    def find_ble_device_for_uuid(
        self,
        tile_uuid: str,
        tiles: list[tuple[BLEDevice, AdvertisementData | None]] | None = None
    ) -> BLEDevice | None:
        """Find BLE device matching a tile UUID.
        
        Tile UUIDs map to MAC addresses - the first 12 chars of UUID
        match the MAC address (without colons).
        
        Args:
            tile_uuid: The tile UUID from API
            tiles: Optional list of scanned tiles (uses cache if not provided)
            
        Returns:
            Matching BLEDevice or None
        """
        # First check cache
        cached_mac = self.cache.get_mac_for_uuid(tile_uuid)
        if cached_mac:
            cached_device = self.cache.get_device(cached_mac)
            if cached_device:
                _LOGGER.debug("Cache hit for UUID %s -> %s", tile_uuid[:8], cached_mac)
                return cached_device
        
        # Use provided tiles or cache
        if tiles is None:
            tiles = self.cache.discovered_tiles
        
        if not tiles:
            return None
        
        # UUID to MAC matching
        # Tile UUID format: cd46a6a4ddad54f0...
        # MAC format: CD:46:A6:A4:DD:AD
        tile_uuid_short = tile_uuid.replace(":", "").replace("-", "").lower()[:12]
        
        for device, adv_data in tiles:
            addr_short = device.address.replace(":", "").lower()
            
            # Direct match
            if addr_short == tile_uuid_short or addr_short.startswith(tile_uuid_short):
                self.cache.cache_mapping(tile_uuid, device.address)
                return device
            
            # Reverse match (MAC might be in different order)
            if tile_uuid_short.startswith(addr_short):
                self.cache.cache_mapping(tile_uuid, device.address)
                return device
        
        # No exact match - return first tile if we only have one
        if len(tiles) == 1:
            device = tiles[0][0]
            _LOGGER.warning("No UUID match, using only discovered Tile: %s", device.address)
            self.cache.cache_mapping(tile_uuid, device.address)
            return device
        
        return None
    
    async def find_tile_ble(
        self,
        tile_uuid: str,
        scan_timeout: float = 10.0,
        force_scan: bool = False
    ) -> BLEDevice | None:
        """Find a Tile via BLE, using cache when possible.
        
        Args:
            tile_uuid: The tile UUID from API
            scan_timeout: Scan timeout if scanning needed
            force_scan: Force new scan even if cached
            
        Returns:
            BLEDevice or None
        """
        # Try cache first
        if not force_scan:
            cached_mac = self.cache.get_mac_for_uuid(tile_uuid)
            if cached_mac:
                cached_device = self.cache.get_device(cached_mac)
                if cached_device:
                    return cached_device
        
        # Scan for tiles
        tiles = await self.scan_for_tiles(timeout=scan_timeout, force_refresh=force_scan)
        
        # Find matching device
        return self.find_ble_device_for_uuid(tile_uuid, tiles)
    
    async def ring_tile(
        self,
        tile: TileDevice,
        volume: str = "medium",
        duration: int = 5,
        song_id: int | None = None,
        connection_timeout: float | None = None,
        auth_timeout: float | None = None
    ) -> bool:
        """Ring a Tile.
        
        Handles the full flow:
        1. Find Tile via BLE (using cache)
        2. Connect and authenticate
        3. Send ring command
        4. Disconnect
        
        Args:
            tile: TileDevice from API/coordinator
            volume: Volume level ("low", "medium", "high", "auto")
            duration: Ring duration in seconds
            song_id: Optional song ID (None = use tile's selected song)
            connection_timeout: BLE connection timeout (default from const.py)
            auth_timeout: Authentication timeout (default from const.py)
            
        Returns:
            True if successful, False otherwise
        """
        # Use defaults from const.py if not specified
        if connection_timeout is None:
            connection_timeout = BLE_CONNECTION_TIMEOUT
        if auth_timeout is None:
            auth_timeout = BLE_AUTH_TIMEOUT
            
        if not tile.auth_key:
            _LOGGER.error("Tile %s has no auth key", tile.name)
            return False
        
        # Find device via BLE
        device = await self.find_tile_ble(tile.tile_uuid)
        
        if not device:
            # Try forced scan if cache miss
            _LOGGER.info("Tile not found in cache, forcing BLE scan...")
            device = await self.find_tile_ble(tile.tile_uuid, force_scan=True)
        
        if not device:
            _LOGGER.error("Could not find Tile %s via Bluetooth", tile.name)
            return False
        
        _LOGGER.info("Ringing Tile %s @ %s", tile.name, device.address)
        
        # Connect and authenticate
        client = None
        try:
            client = BleakClient(device, timeout=connection_timeout)
            await client.connect()
            
            if not client.is_connected:
                _LOGGER.error("Failed to connect to Tile %s", tile.name)
                return False
            
            _LOGGER.debug("Connected to %s, authenticating...", device.address)
            
            # Authenticate
            auth = TileAuthenticator(client, tile.auth_key)
            
            if not await auth.authenticate(timeout=auth_timeout):
                _LOGGER.error("Authentication failed for Tile %s", tile.name)
                return False
            
            _LOGGER.debug("Authenticated, sending ring...")
            
            # Send ring
            volume_bytes = TileVolume.from_string(volume)
            success = await auth.send_ring(volume_bytes, duration, song_id or 0)
            
            if success:
                _LOGGER.info("Ring sent successfully to %s", tile.name)
            
            return success
            
        except Exception as e:
            _LOGGER.error("Error ringing Tile %s: %s", tile.name, e)
            # Clear cache on error - device might have moved
            if tile.tile_uuid in self.cache.uuid_to_mac:
                self.cache.uuid_to_mac.pop(tile.tile_uuid)
            return False
            
        finally:
            if client and client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    
    def clear_cache(self) -> None:
        """Clear all caches."""
        self.cache = TileBleCache()
        _LOGGER.info("Tile BLE cache cleared")
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "uuid_mappings": len(self.cache.uuid_to_mac),
            "cached_devices": len(self.cache.mac_to_device),
            "discovered_tiles": len(self.cache.discovered_tiles),
            "last_scan": datetime.fromtimestamp(self.cache.last_scan).isoformat() if self.cache.last_scan else None,
            "scan_stale": self.cache.is_scan_stale(),
        }


# Global service instance per hass
_tile_services: dict[int, TileService] = {}


def get_tile_service(hass: HomeAssistant) -> TileService:
    """Get or create TileService instance for a Home Assistant instance."""
    hass_id = id(hass)
    if hass_id not in _tile_services:
        _tile_services[hass_id] = TileService(hass)
    return _tile_services[hass_id]


async def async_cleanup_services(hass: HomeAssistant) -> None:
    """Cleanup service instance when Home Assistant stops."""
    hass_id = id(hass)
    if hass_id in _tile_services:
        del _tile_services[hass_id]
