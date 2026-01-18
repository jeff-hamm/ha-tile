#!/usr/bin/env python3
"""
Tile Bluetooth Authentication Test - Standalone

Minimal test script that uses the main tile_auth module.
This script is for testing outside of Home Assistant.

Usage:
    # Test authentication and ring
    python test_ble_auth.py --name "Crewtopia Shed" --volume low --duration 2
    
    # Just test authentication (no ring)
    python test_ble_auth.py --name "Crewtopia Shed" --auth-only
    
    # Scan for nearby Tiles
    python test_ble_auth.py --scan
    
    # Debug mode with verbose logging
    python test_ble_auth.py --name "Crewtopia Shed" --debug
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

import aiohttp
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tile_auth import (
    TileAuthenticator,
    TileVolume,
    FEED_SERVICE_UUID,
)

# Credentials - set these or use environment variables
TILE_EMAIL = os.environ.get("TILE_EMAIL", "jeff.hamm@gmail.com")
TILE_PASSWORD = os.environ.get("TILE_PASSWORD", "ckWM^!g4*YtAye4k")

# API Constants
TILE_API_BASE = "https://production.tile-api.com/api/v1"
TILE_CLIENT_UUID = "26726553-703b-3998-9f0e-c5f256caaf6d"
TILE_APP_ID = "android-tile-production"
TILE_APP_VERSION = "2.109.0.4485"
TILE_USER_AGENT = "Tile/android/2.109.0/4485 (Unknown; Android11)"

_LOGGER = logging.getLogger(__name__)


class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"


def log(msg: str, color: str = "", symbol: str = "") -> None:
    if symbol:
        print(f"{color}{symbol}{Colors.RESET} {msg}")
    else:
        print(f"{color}{msg}{Colors.RESET}")


def log_step(msg: str) -> None:
    log(msg, Colors.CYAN, "→")


def log_success(msg: str) -> None:
    log(msg, Colors.GREEN, "✓")


def log_error(msg: str) -> None:
    log(msg, Colors.RED, "✗")


def log_warning(msg: str) -> None:
    log(msg, Colors.YELLOW, "⚠")


def log_info(msg: str) -> None:
    log(msg, Colors.BLUE, "ℹ")


async def scan_for_tiles(timeout: float = 10.0) -> list[tuple[BLEDevice, AdvertisementData]]:
    """Scan for nearby Tile devices."""
    log_step(f"Scanning for Tiles ({timeout}s)...")
    tiles = []
    
    def detection_callback(device: BLEDevice, adv_data: AdvertisementData):
        service_uuids = [str(u).lower() for u in (adv_data.service_uuids or [])]
        service_data_keys = [str(k).lower() for k in (adv_data.service_data or {}).keys()]
        all_services = service_uuids + service_data_keys
        
        is_tile = any(
            "feed" in s or "feec" in s or
            FEED_SERVICE_UUID.lower() in s or
            "0000feed" in s or "0000feec" in s
            for s in all_services
        )
        
        if device.name and device.name.lower() == "tile":
            is_tile = True
        
        if is_tile:
            if device.address not in [t[0].address for t in tiles]:
                tiles.append((device, adv_data))
                log_info(f"Found: {device.name or 'Unknown'} @ {device.address} (RSSI: {adv_data.rssi})")
    
    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    
    log_success(f"Found {len(tiles)} Tile(s)")
    return tiles


async def get_tile_from_api(
    tile_name: str,
    email: str = TILE_EMAIL,
    password: str = TILE_PASSWORD
) -> tuple[str, str, str] | None:
    """Fetch tile info from Tile API by name.
    
    Returns: (tile_uuid, auth_key, product) or None
    """
    log_step(f"Fetching tile '{tile_name}' from Tile API...")
    
    headers = {
        "User-Agent": TILE_USER_AGENT,
        "tile_app_id": TILE_APP_ID,
        "tile_app_version": TILE_APP_VERSION,
        "tile_client_uuid": TILE_CLIENT_UUID,
        "tile_request_timestamp": str(int(datetime.now().timestamp() * 1000)),
    }
    
    async with aiohttp.ClientSession() as session:
        # Login
        login_url = f"{TILE_API_BASE}/clients/{TILE_CLIENT_UUID}/sessions"
        login_headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
        
        async with session.post(
            login_url,
            headers=login_headers,
            data={"email": email, "password": password}
        ) as resp:
            result = await resp.json()
            if result.get("result_code") != 0:
                log_error(f"Login failed: {result.get('result', {}).get('message')}")
                return None
            cookie = resp.headers.get("Set-Cookie")
            headers["Cookie"] = cookie
            log_success("Logged in to Tile API")
        
        # Get groups to find tile UUID
        groups_url = f"{TILE_API_BASE}/users/groups"
        async with session.get(groups_url, headers=headers, params={"last_modified_timestamp": "0"}) as resp:
            result = await resp.json()
            if result.get("result_code") != 0:
                log_error("Failed to get groups")
                return None
        
        nodes = result.get("result", {}).get("nodes", {})
        tile_uuid = None
        
        for uuid, data in nodes.items():
            if data.get("node_type") == "GROUP":
                continue
            name = data.get("name", "")
            if name.lower() == tile_name.lower():
                tile_uuid = uuid
                break
        
        if not tile_uuid:
            log_error(f"Tile '{tile_name}' not found")
            available = [d.get("name") for d in nodes.values() if d.get("node_type") != "GROUP" and d.get("name")]
            log_info(f"Available tiles: {available}")
            return None
        
        log_info(f"Found tile UUID: {tile_uuid}")
        
        # Get tile details with auth key
        tile_url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        async with session.get(tile_url, headers=headers) as resp:
            result = await resp.json()
            if result.get("result_code") != 0:
                log_error("Failed to get tile details")
                return None
        
        tile_data = result.get("result", {})
        auth_key = tile_data.get("auth_key", "")
        product = tile_data.get("product", "")
        
        if not auth_key:
            log_error("No auth_key in tile data")
            return None
        
        log_success(f"Got auth key ({len(auth_key)} chars) for product: {product}")
        return (tile_uuid, auth_key, product)


async def find_tile_ble(tile_uuid: str, scan_timeout: float = 10.0) -> BLEDevice | None:
    """Find a Tile by UUID via BLE scan."""
    tiles = await scan_for_tiles(scan_timeout)
    
    tile_uuid_short = tile_uuid.replace(":", "").replace("-", "").lower()[:12]
    
    for device, adv_data in tiles:
        addr_short = device.address.replace(":", "").lower()
        
        if addr_short.startswith(tile_uuid_short) or tile_uuid_short.startswith(addr_short):
            log_success(f"Found matching Tile: {device.address}")
            return device
    
    if tiles:
        log_warning("No exact UUID match, using first Tile found")
        return tiles[0][0]
    
    return None


async def test_auth_and_ring(
    tile_name: str,
    volume: str = "medium",
    duration: int = 5,
    auth_only: bool = False,
    scan_timeout: float = 10.0
) -> bool:
    """Main test: authenticate and optionally ring a Tile."""
    
    print("\n" + "=" * 60)
    print(f"  Tile Authentication Test: {tile_name}")
    print("=" * 60 + "\n")
    
    # Step 1: Get tile info from API
    tile_info = await get_tile_from_api(tile_name)
    if not tile_info:
        log_error("Failed to get tile info from API")
        return False
    
    tile_uuid, auth_key, product = tile_info
    
    # Step 2: Find tile via BLE
    print()
    device = await find_tile_ble(tile_uuid, scan_timeout)
    if not device:
        log_error("Could not find Tile via Bluetooth")
        return False
    
    # Step 3: Connect and authenticate using TileAuthenticator
    print()
    log_step(f"Connecting to {device.address}...")
    
    try:
        client = BleakClient(device, timeout=45.0)
        await client.connect()
        
        if not client.is_connected:
            log_error("Failed to connect")
            return False
        
        log_success("Connected")
        
        auth = TileAuthenticator(client, auth_key)
        
        print()
        log_step("Starting authentication sequence...")
        
        success = await auth.authenticate(timeout=15.0)
        
        if success:
            log_success("Authentication successful!")
            print()
            log_info(f"Tile ID: {auth.tile_id}")
            log_info(f"Firmware: {auth.firmware}")
            log_info(f"Model: {auth.model}")
            log_info(f"Hardware: {auth.hardware}")
            
            if not auth_only:
                print()
                log_step(f"Sending ring: volume={volume}, duration={duration}s")
                
                volume_bytes = TileVolume.from_string(volume)
                ring_success = await auth.send_ring(volume_bytes, duration)
                
                if ring_success:
                    log_success("Ring command sent!")
                else:
                    log_warning("Ring may have failed")
        else:
            log_error("Authentication failed")
        
        await client.disconnect()
        return success
        
    except Exception as e:
        log_error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Tile BLE Authentication Test")
    parser.add_argument("--name", help="Tile name to ring (e.g., 'Crewtopia Shed')")
    parser.add_argument("--volume", default="medium", choices=["low", "medium", "high", "auto"])
    parser.add_argument("--duration", type=int, default=5, help="Ring duration (1-30)")
    parser.add_argument("--scan", action="store_true", help="Just scan for Tiles")
    parser.add_argument("--auth-only", action="store_true", help="Only authenticate, don't ring")
    parser.add_argument("--scan-timeout", type=float, default=10.0, help="BLE scan timeout")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s: %(message)s"
        )
    
    if args.scan:
        tiles = await scan_for_tiles(args.scan_timeout)
        print()
        if tiles:
            print("Found Tiles:")
            for device, adv in tiles:
                rssi = adv.rssi if adv else "?"
                print(f"  {device.name or 'Unknown':20} @ {device.address} (RSSI: {rssi})")
        return
    
    if not args.name:
        parser.print_help()
        print("\nError: --name is required (or use --scan)")
        sys.exit(1)
    
    success = await test_auth_and_ring(
        args.name,
        args.volume,
        args.duration,
        args.auth_only,
        args.scan_timeout
    )
    
    print()
    if success:
        log_success("Test completed successfully!")
    else:
        log_error("Test failed")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
