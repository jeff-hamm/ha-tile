#!/usr/bin/env python3
"""
Tile Tracker Integration Tests

Standalone test script for the Tile API - can run without Home Assistant.
Reads credentials from environment variables or uses defaults.

Usage:
    # With environment variables
    TILE_EMAIL=you@example.com TILE_PASSWORD=yourpass python test_tile_api.py
    
    # Or run directly (uses test credentials if set)
    python test_tile_api.py
    
    # Specific tests
    python test_tile_api.py --test login
    python test_tile_api.py --test tiles
    python test_tile_api.py --test details
    python test_tile_api.py --test states
"""
import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

# API Constants
TILE_API_BASE = "https://production.tile-api.com/api/v1"
TILE_CLIENT_UUID = "26726553-703b-3998-9f0e-c5f256caaf6d"
TILE_APP_ID = "android-tile-production"
TILE_APP_VERSION = "2.109.0.4485"
TILE_USER_AGENT = "Tile/android/2.109.0/4485 (Unknown; Android11)"


@dataclass
class TileDevice:
    """Simplified TileDevice for testing."""
    
    tile_uuid: str
    name: str
    auth_key: str
    archetype: str
    product: str
    advertised_rssi: float | None = None
    speed: float | None = None
    ring_state: str | None = None
    connection_state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    last_timestamp: datetime | None = None
    battery_status: str | None = None

    @classmethod
    def from_api_response(cls, tile_uuid: str, data: dict[str, Any]) -> "TileDevice":
        """Create TileDevice from API response."""
        last_state = data.get("last_tile_state", {}) or {}
        timestamp = last_state.get("timestamp")
        last_ts = None
        if timestamp:
            try:
                last_ts = datetime.fromtimestamp(timestamp / 1000)
            except (ValueError, TypeError, OSError):
                pass
        return cls(
            tile_uuid=tile_uuid,
            name=data.get("name", "Unknown Tile"),
            auth_key=data.get("auth_key", ""),
            archetype=data.get("archetype", "UNKNOWN"),
            product=data.get("product", ""),
            advertised_rssi=last_state.get("advertised_rssi"),
            speed=last_state.get("speed"),
            ring_state=last_state.get("ring_state"),
            connection_state=last_state.get("connection_state"),
            latitude=last_state.get("latitude"),
            longitude=last_state.get("longitude"),
            last_timestamp=last_ts,
            battery_status=data.get("battery_status"),
        )

    @property
    def tile_type(self) -> str:
        """Return tile type."""
        return self.product or self.archetype

    @property
    def is_physical_tile(self) -> bool:
        """Return True if this is a physical Tile (not a phone)."""
        return bool(self.auth_key) and not self.tile_uuid.startswith("p!")


class TileApiTester:
    """Test client for Tile API."""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.session: aiohttp.ClientSession | None = None
        self.cookie: str | None = None

    def _get_headers(self, include_cookie: bool = True) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "User-Agent": TILE_USER_AGENT,
            "tile_app_id": TILE_APP_ID,
            "tile_app_version": TILE_APP_VERSION,
            "tile_client_uuid": TILE_CLIENT_UUID,
            "tile_request_timestamp": str(int(datetime.now().timestamp() * 1000)),
        }
        if include_cookie and self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def login(self) -> dict:
        """Login and return response."""
        url = f"{TILE_API_BASE}/clients/{TILE_CLIENT_UUID}/sessions"
        headers = self._get_headers(include_cookie=False)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        async with self.session.post(
            url, headers=headers, data={"email": self.email, "password": self.password}
        ) as resp:
            self.cookie = resp.headers.get("Set-Cookie")
            return await resp.json()

    async def get_groups(self) -> dict:
        """Get user groups (contains tile list)."""
        url = f"{TILE_API_BASE}/users/groups"
        params = {"last_modified_timestamp": "0"}
        async with self.session.get(
            url, headers=self._get_headers(), params=params
        ) as resp:
            return await resp.json()

    async def get_tile(self, tile_uuid: str) -> dict:
        """Get specific tile details."""
        url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        async with self.session.get(url, headers=self._get_headers()) as resp:
            return await resp.json()

    async def get_tile_states(self) -> dict:
        """Get all tile states."""
        url = f"{TILE_API_BASE}/tiles/tile_states"
        async with self.session.get(url, headers=self._get_headers()) as resp:
            return await resp.json()


async def test_login(tester: TileApiTester) -> bool:
    """Test login functionality."""
    print("=" * 60)
    print("TEST: Login")
    print("=" * 60)
    
    result = await tester.login()
    success = result.get("result_code") == 0
    
    if success:
        user = result.get("result", {}).get("user", {})
        print(f"✓ Login successful")
        print(f"  User: {user.get('full_name')} ({user.get('email')})")
        print(f"  Status: {user.get('status')}")
        session_exp = result.get("result", {}).get("session_expiration_timestamp")
        if session_exp:
            exp_time = datetime.fromtimestamp(session_exp / 1000)
            print(f"  Session expires: {exp_time}")
    else:
        error = result.get("result", {}).get("message", "Unknown error")
        print(f"✗ Login failed: {error}")
    
    print()
    return success


async def test_get_tiles(tester: TileApiTester) -> list[TileDevice]:
    """Test getting all tiles."""
    print("=" * 60)
    print("TEST: Get Tiles (with full details)")
    print("=" * 60)
    
    # Get groups to find tile UUIDs
    result = await tester.get_groups()
    if result.get("result_code") != 0:
        print(f"✗ Failed to get groups: {result.get('result', {}).get('message')}")
        return []
    
    nodes = result.get("result", {}).get("nodes", {})
    
    # Filter to active tiles
    tile_uuids = []
    skipped = {"dead": 0, "invisible": 0, "groups": 0}
    
    for tile_uuid, tile_data in nodes.items():
        if tile_data.get("node_type") == "GROUP":
            skipped["groups"] += 1
            continue
        if tile_data.get("is_dead", False):
            skipped["dead"] += 1
            continue
        if not tile_data.get("visible", True):
            skipped["invisible"] += 1
            continue
        tile_uuids.append(tile_uuid)
    
    print(f"Found {len(tile_uuids)} active tiles")
    print(f"  Skipped: {skipped['dead']} dead, {skipped['invisible']} invisible, {skipped['groups']} groups")
    print()
    
    # Get full details for each tile
    tiles = []
    for tile_uuid in tile_uuids:
        result = await tester.get_tile(tile_uuid)
        if result.get("result_code") == 0:
            tile = TileDevice.from_api_response(tile_uuid, result.get("result", {}))
            tiles.append(tile)
            
            # Print tile info
            tile_icon = "🔷" if tile.is_physical_tile else "📱"
            print(f"{tile_icon} {tile.name}")
            print(f"   UUID: {tile.tile_uuid}")
            print(f"   Type: {tile.tile_type}")
            print(f"   RSSI: {tile.advertised_rssi}")
            print(f"   Ring: {tile.ring_state} | Connection: {tile.connection_state}")
            if tile.latitude:
                print(f"   Location: {tile.latitude:.4f}, {tile.longitude:.4f}")
            else:
                print(f"   Location: Unknown")
            print(f"   Last seen: {tile.last_timestamp or 'Unknown'}")
            print(f"   Battery: {tile.battery_status or 'N/A'}")
            print(f"   Auth key: {'Yes' if tile.auth_key else 'No (phone)'}")
            print()
    
    print(f"✓ Retrieved {len(tiles)} tiles")
    physical = sum(1 for t in tiles if t.is_physical_tile)
    phones = len(tiles) - physical
    print(f"  Physical tiles: {physical}")
    print(f"  Phone tiles: {phones}")
    print()
    
    return tiles


async def test_tile_details(tester: TileApiTester, tile_uuid: str) -> dict | None:
    """Test getting specific tile details (raw JSON)."""
    print("=" * 60)
    print(f"TEST: Tile Details (raw) - {tile_uuid}")
    print("=" * 60)
    
    result = await tester.get_tile(tile_uuid)
    
    if result.get("result_code") == 0:
        print(f"✓ Got tile details")
        print(json.dumps(result, indent=2, default=str))
        return result
    else:
        print(f"✗ Failed: {result.get('result', {}).get('message')}")
        return None


async def test_tile_states(tester: TileApiTester) -> dict | None:
    """Test getting all tile states."""
    print("=" * 60)
    print("TEST: Tile States")
    print("=" * 60)
    
    result = await tester.get_tile_states()
    
    if result.get("result_code") == 0:
        states = result.get("result", [])
        print(f"✓ Got states for {len(states)} tiles")
        print()
        
        for state in states:
            tile_id = state.get("tile_id", "unknown")
            loc = state.get("location", {})
            lost = state.get("mark_as_lost", {})
            
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            ts = loc.get("location_timestamp")
            is_lost = lost.get("is_lost", False)
            
            last_seen = ""
            if ts:
                try:
                    last_seen = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            lost_icon = "🔴" if is_lost else "🟢"
            print(f"{lost_icon} {tile_id}")
            if lat and lon:
                print(f"   Location: {lat:.4f}, {lon:.4f}")
            print(f"   Last seen: {last_seen or 'Unknown'}")
            if is_lost:
                print(f"   ⚠️  Marked as LOST")
            print()
        
        return result
    else:
        print(f"✗ Failed: {result.get('result', {}).get('message')}")
        return None


async def run_all_tests(email: str, password: str):
    """Run all tests."""
    async with TileApiTester(email, password) as tester:
        # Test 1: Login
        if not await test_login(tester):
            print("❌ Login failed, cannot continue")
            return False
        
        # Test 2: Get all tiles with details
        tiles = await test_get_tiles(tester)
        
        # Test 3: Get tile states
        await test_tile_states(tester)
        
        # Test 4: Get raw details for first physical tile
        physical_tiles = [t for t in tiles if t.is_physical_tile]
        if physical_tiles:
            await test_tile_details(tester, physical_tiles[0].tile_uuid)
        
        print("=" * 60)
        print("✅ All tests completed!")
        print("=" * 60)
        return True


async def run_single_test(email: str, password: str, test_name: str):
    """Run a single test."""
    async with TileApiTester(email, password) as tester:
        # Always login first
        if not await test_login(tester):
            print("❌ Login failed")
            return False
        
        if test_name == "login":
            return True
        elif test_name == "tiles":
            await test_get_tiles(tester)
        elif test_name == "states":
            await test_tile_states(tester)
        elif test_name == "details":
            tiles = await test_get_tiles(tester)
            if tiles:
                await test_tile_details(tester, tiles[0].tile_uuid)
        else:
            print(f"Unknown test: {test_name}")
            return False
        
        return True


def main():
    parser = argparse.ArgumentParser(description="Test Tile API")
    parser.add_argument("--test", choices=["login", "tiles", "details", "states"],
                        help="Run specific test only")
    parser.add_argument("--email", help="Tile account email")
    parser.add_argument("--password", help="Tile account password")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()
    
    # Get credentials from args, env, or error
    email = args.email or os.environ.get("TILE_EMAIL")
    password = args.password or os.environ.get("TILE_PASSWORD")
    
    if not email or not password:
        print("Error: Tile credentials required")
        print("  Set TILE_EMAIL and TILE_PASSWORD environment variables")
        print("  Or use --email and --password arguments")
        sys.exit(1)
    
    if args.test:
        asyncio.run(run_single_test(email, password, args.test))
    else:
        asyncio.run(run_all_tests(email, password))


if __name__ == "__main__":
    main()
