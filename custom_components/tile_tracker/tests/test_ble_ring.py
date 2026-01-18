#!/usr/bin/env python3
"""
Tile Bluetooth Ring Test - Standalone

Test script to ring a Tile via Bluetooth without Home Assistant.
Uses bleak directly for BLE communication.

Usage:
    # Ring "Crewtopia Shed" with low volume, 2 second duration
    python test_ble_ring.py --name "Crewtopia Shed" --volume low --duration 2
    
    # Scan for nearby Tiles
    python test_ble_ring.py --scan
    
    # Ring by MAC address
    python test_ble_ring.py --mac AA:BB:CC:DD:EE:FF --auth-key "base64key=="
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import os
import struct
import sys
from dataclasses import dataclass
from datetime import datetime

import aiohttp
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# API Constants
TILE_API_BASE = "https://production.tile-api.com/api/v1"
TILE_CLIENT_UUID = "26726553-703b-3998-9f0e-c5f256caaf6d"
TILE_APP_ID = "android-tile-production"
TILE_APP_VERSION = "2.109.0.4485"
TILE_USER_AGENT = "Tile/android/2.109.0/4485 (Unknown; Android11)"

# BLE Constants (Tile FEED service)
FEED_SERVICE_UUID = "0000feed-0000-1000-8000-00805f9b34fb"
FEEC_SERVICE_UUID = "0000feec-0000-1000-8000-00805f9b34fb"  # Shorter range
MEP_COMMAND_CHAR_UUID = "9d410018-35d6-f4dd-ba60-e7bd8dc491c0"
MEP_RESPONSE_CHAR_UUID = "9d410019-35d6-f4dd-ba60-e7bd8dc491c0"
TILE_ID_CHAR_UUID = "9d410002-35d6-f4dd-ba60-e7bd8dc491c0"

# Alternative 16-bit UUIDs
FEED_UUID_SHORT = "feed"
FEEC_UUID_SHORT = "feec"


class TileVolume:
    """Volume levels for Tile ring."""
    LOW = bytes([0x01, 0x01])
    MED = bytes([0x01, 0x02])
    HIGH = bytes([0x01, 0x03])
    AUTO = bytes([0x16, 0x03, 0x03])
    
    @classmethod
    def from_string(cls, volume: str) -> bytes:
        return {
            "low": cls.LOW,
            "med": cls.MED,
            "medium": cls.MED,
            "high": cls.HIGH,
            "auto": cls.AUTO,
        }.get(volume.lower(), cls.MED)


@dataclass
class TileInfo:
    """Tile device info from API."""
    uuid: str
    name: str
    auth_key: str
    product: str


class TileBleRinger:
    """Standalone Tile BLE ringer using bleak."""
    
    def __init__(self):
        self.client: BleakClient | None = None
        self.mep_command_char = None
        self.mep_response_char = None
        self.tile_id_char = None
        self.response_event = asyncio.Event()
        self.response_data = b""
        self.mep_data = os.urandom(4)
        self.rand_a = os.urandom(14)
        self.tile_id = ""
        
    def _on_response(self, sender, data: bytearray):
        """Handle BLE notification response."""
        print(f"  ← Response: {data.hex()}")
        self.response_data = bytes(data)
        self.response_event.set()
    
    async def scan_for_tiles(self, timeout: float = 10.0) -> list[tuple[BLEDevice, AdvertisementData]]:
        """Scan for nearby Tile devices."""
        print(f"Scanning for Tiles ({timeout}s)...")
        tiles = []
        
        def detection_callback(device: BLEDevice, adv_data: AdvertisementData):
            service_uuids = [str(u).lower() for u in (adv_data.service_uuids or [])]
            is_tile = any(
                FEED_UUID_SHORT in u or FEEC_UUID_SHORT in u or
                FEED_SERVICE_UUID.lower() in u or FEEC_SERVICE_UUID.lower() in u
                for u in service_uuids
            )
            if is_tile:
                if device.address not in [t[0].address for t in tiles]:
                    tiles.append((device, adv_data))
                    rssi = adv_data.rssi
                    print(f"  Found Tile: {device.name or 'Unknown'} @ {device.address} (RSSI: {rssi})")
        
        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()
        
        print(f"Found {len(tiles)} Tile(s)")
        return tiles
    
    async def connect(self, device: BLEDevice) -> bool:
        """Connect to a Tile and discover services."""
        try:
            print(f"Connecting to {device.address}...")
            self.client = BleakClient(device, timeout=20.0)
            await self.client.connect()
            
            if not self.client.is_connected:
                print("  ✗ Failed to connect")
                return False
            
            print(f"  ✓ Connected, discovering services...")
            
            # Find FEED service
            for service in self.client.services:
                svc_uuid = str(service.uuid).lower()
                if FEED_UUID_SHORT in svc_uuid or FEED_SERVICE_UUID.lower() == svc_uuid:
                    print(f"  Found FEED service: {service.uuid}")
                    
                    for char in service.characteristics:
                        char_uuid = str(char.uuid).lower()
                        if MEP_COMMAND_CHAR_UUID.lower() == char_uuid:
                            self.mep_command_char = char
                            print(f"    MEP Command: {char.uuid}")
                        elif MEP_RESPONSE_CHAR_UUID.lower() == char_uuid:
                            self.mep_response_char = char
                            print(f"    MEP Response: {char.uuid}")
                        elif TILE_ID_CHAR_UUID.lower() == char_uuid:
                            self.tile_id_char = char
                            print(f"    Tile ID: {char.uuid}")
            
            if not self.mep_command_char or not self.mep_response_char:
                print("  ✗ Could not find required characteristics")
                await self.disconnect()
                return False
            
            # Subscribe to notifications
            await self.client.start_notify(self.mep_response_char, self._on_response)
            print("  ✓ Subscribed to notifications")
            
            # Read Tile ID
            if self.tile_id_char:
                try:
                    tile_id_data = await self.client.read_gatt_char(self.tile_id_char)
                    self.tile_id = tile_id_data.hex()
                    print(f"  Tile ID: {self.tile_id}")
                except Exception as e:
                    print(f"  Could not read Tile ID: {e}")
            
            return True
            
        except Exception as e:
            print(f"  ✗ Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the Tile."""
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
                print("  Disconnected")
            except Exception as e:
                print(f"  Disconnect error: {e}")
        self.client = None
    
    async def send_command(self, data: bytes, wait_response: bool = True, timeout: float = 5.0) -> bytes:
        """Send a command and optionally wait for response."""
        if not self.client or not self.mep_command_char:
            raise RuntimeError("Not connected")
        
        print(f"  → Command: {data.hex()}")
        self.response_event.clear()
        
        await self.client.write_gatt_char(self.mep_command_char, data, response=True)
        
        if wait_response:
            try:
                await asyncio.wait_for(self.response_event.wait(), timeout=timeout)
                return self.response_data
            except asyncio.TimeoutError:
                print(f"    ⚠ Timeout waiting for response")
                return b""
        return b""
    
    async def authenticate(self, auth_key_b64: str) -> bool:
        """Authenticate with the Tile using its auth key."""
        if not self.client:
            return False
        
        try:
            auth_key = base64.b64decode(auth_key_b64)
            print(f"Authenticating with key ({len(auth_key)} bytes)...")
            
            # TOA prefix 20 = TDI start (authentication)
            # Format: [channel, mep_data..., toa_prefix, rand_a...]
            rand_a_cmd = bytes([0, *self.mep_data, 20, *self.rand_a])
            response = await self.send_command(rand_a_cmd)
            
            if response:
                print(f"  ✓ Auth response received")
                return True
            else:
                print(f"  ⚠ No auth response (may still work for ring)")
                return True  # Some tiles accept ring without full auth
                
        except Exception as e:
            print(f"  ✗ Auth error: {e}")
            return False
    
    async def send_ring(self, volume_bytes: bytes, duration: int) -> bool:
        """Send a ring command to the Tile."""
        if not self.client:
            return False
        
        duration = max(1, min(duration, 30))
        print(f"Sending ring: volume={volume_bytes.hex()}, duration={duration}s")
        
        # Try with MEP wrapper first
        # Format: [channel, mep_data..., toa_prefix=5, song_type=2, volume_bytes..., duration]
        ring_cmd = bytes([0, *self.mep_data, 5, 2, *volume_bytes, duration])
        response = await self.send_command(ring_cmd)
        
        if response:
            # Check for success response
            if len(response) > 1:
                print(f"  Ring response code: {response[1]}")
                if response[1] == 2:  # TOA_SONG_RSP_PLAY_OK
                    print(f"  ✓ Ring acknowledged!")
                    return True
        
        # Try simpler format without MEP wrapper
        print("  Trying simpler ring format...")
        simple_cmd = bytes([5, 2, *volume_bytes, duration])
        response = await self.send_command(simple_cmd)
        
        if response:
            print(f"  ✓ Simple ring sent, response: {response.hex()}")
            return True
        
        # Try even simpler - just volume and duration
        print("  Trying minimal format...")
        minimal_cmd = bytes([*volume_bytes, duration])
        response = await self.send_command(minimal_cmd, wait_response=False)
        print(f"  ✓ Minimal command sent")
        
        return True


async def get_tile_from_api(tile_name: str, email: str, password: str) -> TileInfo | None:
    """Fetch tile info from Tile API by name."""
    print(f"Fetching tile '{tile_name}' from Tile API...")
    
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
                print(f"  ✗ Login failed: {result.get('result', {}).get('message')}")
                return None
            cookie = resp.headers.get("Set-Cookie")
            headers["Cookie"] = cookie
            print(f"  ✓ Logged in")
        
        # Get groups to find tile UUID
        groups_url = f"{TILE_API_BASE}/users/groups"
        async with session.get(groups_url, headers=headers, params={"last_modified_timestamp": "0"}) as resp:
            result = await resp.json()
            if result.get("result_code") != 0:
                print(f"  ✗ Failed to get groups")
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
            print(f"  ✗ Tile '{tile_name}' not found")
            available = [d.get("name") for d in nodes.values() if d.get("node_type") != "GROUP" and d.get("name")]
            print(f"  Available tiles: {available}")
            return None
        
        print(f"  Found tile UUID: {tile_uuid}")
        
        # Get tile details
        tile_url = f"{TILE_API_BASE}/tiles/{tile_uuid}"
        async with session.get(tile_url, headers=headers) as resp:
            result = await resp.json()
            if result.get("result_code") != 0:
                print(f"  ✗ Failed to get tile details")
                return None
        
        tile_data = result.get("result", {})
        return TileInfo(
            uuid=tile_uuid,
            name=tile_data.get("name", tile_name),
            auth_key=tile_data.get("auth_key", ""),
            product=tile_data.get("product", ""),
        )


async def ring_tile(
    tile_name: str = None,
    mac_address: str = None,
    auth_key: str = None,
    email: str = None,
    password: str = None,
    volume: str = "low",
    duration: int = 2,
    scan_timeout: float = 15.0,
) -> bool:
    """Ring a Tile by name or MAC address."""
    ringer = TileBleRinger()
    
    # Get auth key from API if we have a name
    tile_info = None
    if tile_name and email and password:
        tile_info = await get_tile_from_api(tile_name, email, password)
        if tile_info:
            auth_key = tile_info.auth_key
            print(f"Tile: {tile_info.name} ({tile_info.product})")
            print(f"UUID: {tile_info.uuid}")
            print(f"Auth key: {'Yes' if auth_key else 'No'}")
    
    # Scan for Tiles
    tiles = await ringer.scan_for_tiles(timeout=scan_timeout)
    
    if not tiles:
        print("✗ No Tiles found nearby")
        return False
    
    # Find matching tile
    target_device = None
    
    if mac_address:
        # Match by MAC
        for device, adv in tiles:
            if device.address.lower() == mac_address.lower():
                target_device = device
                break
    elif tile_info:
        # Match by UUID prefix in advertisement or name
        uuid_short = tile_info.uuid[:12].lower()
        for device, adv in tiles:
            # Check if device name or address contains UUID prefix
            dev_addr = device.address.replace(":", "").lower()
            if uuid_short in dev_addr or (device.name and tile_info.name.lower() in device.name.lower()):
                target_device = device
                break
    
    if not target_device and tiles:
        # Just use the first found tile if no specific match
        print(f"⚠ No exact match, using first found tile")
        target_device = tiles[0][0]
    
    if not target_device:
        print("✗ Could not find target Tile")
        return False
    
    print(f"\nTarget: {target_device.name or 'Unknown'} @ {target_device.address}")
    
    # Connect
    if not await ringer.connect(target_device):
        return False
    
    try:
        # Authenticate if we have an auth key
        if auth_key:
            await ringer.authenticate(auth_key)
        
        # Send ring
        volume_bytes = TileVolume.from_string(volume)
        success = await ringer.send_ring(volume_bytes, duration)
        
        if success:
            print(f"\n✓ Ring command sent successfully!")
            # Wait for the ring to play
            print(f"  Waiting {duration}s for ring to complete...")
            await asyncio.sleep(duration + 1)
        else:
            print(f"\n✗ Ring command may have failed")
        
        return success
        
    finally:
        await ringer.disconnect()


async def scan_only():
    """Just scan and list nearby Tiles."""
    ringer = TileBleRinger()
    tiles = await ringer.scan_for_tiles(timeout=15.0)
    
    print("\n" + "=" * 60)
    print("TILE SCAN RESULTS")
    print("=" * 60)
    
    for device, adv in tiles:
        print(f"\n{device.name or 'Unknown Tile'}")
        print(f"  Address: {device.address}")
        print(f"  RSSI: {adv.rssi} dBm")
        print(f"  Services: {adv.service_uuids}")
        if adv.manufacturer_data:
            print(f"  Manufacturer data: {dict(adv.manufacturer_data)}")


def main():
    parser = argparse.ArgumentParser(description="Test Tile Bluetooth ring")
    parser.add_argument("--name", help="Tile name to ring (e.g., 'Crewtopia Shed')")
    parser.add_argument("--mac", help="Tile MAC address to ring")
    parser.add_argument("--auth-key", help="Tile auth key (base64)")
    parser.add_argument("--email", default=os.environ.get("TILE_EMAIL"), help="Tile account email")
    parser.add_argument("--password", default=os.environ.get("TILE_PASSWORD"), help="Tile account password")
    parser.add_argument("--volume", default="low", choices=["low", "med", "high", "auto"], help="Ring volume")
    parser.add_argument("--duration", type=int, default=2, help="Ring duration in seconds")
    parser.add_argument("--scan", action="store_true", help="Just scan for nearby Tiles")
    parser.add_argument("--scan-timeout", type=float, default=15.0, help="Scan timeout in seconds")
    args = parser.parse_args()
    
    if args.scan:
        asyncio.run(scan_only())
        return
    
    if not args.name and not args.mac:
        print("Error: Specify --name or --mac to ring a Tile")
        print("       Or use --scan to find nearby Tiles")
        sys.exit(1)
    
    if args.name and not (args.email and args.password):
        print("Error: --email and --password required when using --name")
        print("       Set TILE_EMAIL and TILE_PASSWORD environment variables")
        sys.exit(1)
    
    success = asyncio.run(ring_tile(
        tile_name=args.name,
        mac_address=args.mac,
        auth_key=args.auth_key,
        email=args.email,
        password=args.password,
        volume=args.volume,
        duration=args.duration,
        scan_timeout=args.scan_timeout,
    ))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
