"""Constants for the Tile Tracker integration.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT

Tile BLE protocol implementation based on node-tile by lesleyxyz:
https://github.com/lesleyxyz/node-tile
Licensed under MIT by lesleyxyz.
"""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "tile_tracker"
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"

# Tile API endpoints
TILE_API_BASE: Final = "https://production.tile-api.com/api/v1"
TILE_CLIENT_UUID: Final = "26726553-703b-3998-9f0e-c5f256caaf6d"
TILE_APP_ID: Final = "android-tile-production"
TILE_APP_VERSION: Final = "2.109.0.4485"
TILE_USER_AGENT: Final = "Tile/android/2.109.0/4485 (Unknown; Android11)"

# BLE UUIDs for Tile devices
FEED_SERVICE_UUID: Final = "0000feed-0000-1000-8000-00805f9b34fb"
FEEC_SERVICE_UUID: Final = "0000feec-0000-1000-8000-00805f9b34fb"
MEP_COMMAND_CHAR_UUID: Final = "9d410018-35d6-f4dd-ba60-e7bd8dc491c0"
MEP_RESPONSE_CHAR_UUID: Final = "9d410019-35d6-f4dd-ba60-e7bd8dc491c0"
TILE_ID_CHAR_UUID: Final = "9d410007-35d6-f4dd-ba60-e7bd8dc491c0"

# BLE connection parameters
BLE_CONNECTION_TIMEOUT: Final = 45.0  # seconds
BLE_AUTH_TIMEOUT: Final = 15.0  # seconds
BLE_SCAN_TIMEOUT: Final = 10.0  # seconds

# Cache TTL values
UUID_MAC_CACHE_TTL: Final = 3600  # 1 hour - MAC addresses rarely change
SCAN_CACHE_TTL: Final = 60  # 1 minute - for rapid re-scans

# Services
SERVICE_REFRESH_TILES: Final = "refresh_tiles"
SERVICE_PLAY_SOUND: Final = "play_sound"
SERVICE_SCAN_TILES: Final = "scan_tiles"
SERVICE_CLEAR_CACHE: Final = "clear_cache"

# Service attributes
ATTR_TILE_ID: Final = "tile_id"
ATTR_VOLUME: Final = "volume"
ATTR_DURATION: Final = "duration"
ATTR_SONG_ID: Final = "song_id"

# Song transaction types (TOA prefix 5)
SONG_TYPE_READ_FEATURES: Final = 1
SONG_TYPE_PLAY: Final = 2
SONG_TYPE_STOP: Final = 3
SONG_TYPE_PROGRAM_READY: Final = 4
SONG_TYPE_BLOCK_OK: Final = 5
SONG_TYPE_PROGRAM_COMPLETE: Final = 6
SONG_TYPE_SONG_MAP: Final = 7

# Default song options (fallback if BLE query fails)
DEFAULT_SONGS: Final = [
    {"id": 0, "name": "Default"},
    {"id": 1, "name": "Chirp"},
]

# Config options
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 5  # minutes

# Attribution
ATTRIBUTION: Final = "Data provided by Tile"

# Entity attributes
ATTR_TILE_UUID: Final = "tile_uuid"
ATTR_TILE_TYPE: Final = "tile_type"
ATTR_LAST_TILE_STATE: Final = "last_tile_state"
ATTR_ADVERTISED_RSSI: Final = "advertised_rssi"
ATTR_SPEED: Final = "speed"
ATTR_RING_STATE: Final = "ring_state"
ATTR_FIRMWARE_VERSION: Final = "firmware_version"
ATTR_HARDWARE_VERSION: Final = "hardware_version"
ATTR_BATTERY_STATUS: Final = "battery_status"
ATTR_ARCHETYPE: Final = "archetype"
ATTR_LAST_TIMESTAMP: Final = "last_timestamp"
ATTR_AUTH_KEY: Final = "auth_key"
ATTR_AVAILABLE_SONGS: Final = "available_songs"
ATTR_SELECTED_SONG: Final = "selected_song"

# Volume levels for ring
TILE_VOLUME_LOW: Final = 1
TILE_VOLUME_MED: Final = 2
TILE_VOLUME_HIGH: Final = 3

# Update interval
UPDATE_INTERVAL: Final = 300  # 5 minutes

# Storage
STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.storage"
