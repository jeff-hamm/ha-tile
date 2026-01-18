"""Tile Bluetooth Authentication Protocol Implementation.

Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
Developed with assistance from Claude (Anthropic)

SPDX-License-Identifier: MIT

This module implements the full Tile authentication handshake required for
BLE communication with Tile devices.

Protocol Flow:
1. Subscribe to MEP response notifications
2. TDI Sequence: Request TILE_ID, FIRMWARE, MODEL, HARDWARE (prefix 19)
3. Send RandA (prefix 20) - our random 14 bytes
4. Receive RandT + SresT (prefix 21/27) - Tile's random + signature
5. Send RandA again (prefix 16) - confirm authentication
6. Receive Channel Open (prefix 18) - dedicated channel assignment
7. Send Channel Open ACK: [18, 19]
8. Receive READY (prefix 1) - featuresAvailable, nonceB
9. Now authenticated - can send commands with HMAC

Based on the node-tile library by lesleyxyz:
https://github.com/lesleyxyz/node-tile
node-tile is licensed under MIT by lesleyxyz.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

_LOGGER = logging.getLogger(__name__)

# BLE UUIDs
FEED_SERVICE_UUID = "0000feed-0000-1000-8000-00805f9b34fb"
MEP_COMMAND_CHAR_UUID = "9d410018-35d6-f4dd-ba60-e7bd8dc491c0"
MEP_RESPONSE_CHAR_UUID = "9d410019-35d6-f4dd-ba60-e7bd8dc491c0"
TILE_ID_CHAR_UUID = "9d410007-35d6-f4dd-ba60-e7bd8dc491c0"


class ToaPrefix(IntEnum):
    """TOA (Tile Over Air) message prefixes.
    
    Request vs Response prefixes differ!
    - Request TDI = 19, Response TDI = 20
    - Request AUTH = 20, Response AUTH = 21
    """
    # Response prefixes (what we receive)
    RESERVED = 0
    READY = 1  # Nonce ready, features available
    TOFU_CTL = 2
    ASSERT = 3
    BDADDR = 4
    ERROR = 5
    TDT = 6
    SONG = 7  # Song response
    PPM = 8
    ADV_INT = 9
    TKA = 10
    TAC = 11
    TDG = 12
    TMD = 13
    TCU = 14
    TIME = 15
    TEST = 16
    TFC = 17
    OPEN_CHANNEL = 18  # Channel opened
    CLOSE_CHANNEL = 19  # Channel closed
    TDI_RESPONSE = 20  # Response to TDI request (request is 19)
    AUTH_RESPONSE = 21  # Receive RandT + SresT
    TRM = 25
    TPC = 26
    ASSOCIATE = 27  # Auth association response
    AUTHORIZE = 28
    TUC_DEPRECATED = 29
    TUC = 30
    
    # Request prefixes (what we send - pre-auth)
    TDI_REQUEST = 19  # Request Tile Data Info


class TdiRequest(IntEnum):
    """TDI request types for Tile Data Information."""
    FEATURES = 1  # Request available features
    TILE_ID = 2
    FIRMWARE = 3
    MODEL = 4
    HARDWARE = 5


class SongCommand(IntEnum):
    """Song command types."""
    STOP = 1
    PLAY = 2
    UNKNOWN3 = 3
    PROGRAM_READY = 4
    PROGRAM_DATA = 5
    SONG_MAP = 6


@dataclass
class ToaProcessor:
    """TOA processor state for managing authentication and communication."""
    nonce_a: int = 0
    nonce_t: int = 0
    nonce_b: int = 0
    max_payload_size: int = 20
    features_available: bytes = b""
    channel_opened: bool = False
    got_nonce_packet: bool = False
    
    # Tile info
    tile_id: str = ""
    mac_address: str = ""
    firmware: str = ""
    model: str = ""
    auth_key_hmac: bytes = b""
    security_level: int = 1
    mep_channel_auth_key_hmac: bytes | None = None


@dataclass
class ToaMepProcessor:
    """MEP processor for connectionless and channel communication."""
    MAGIC_PREFIX_BYTES = [16, 19, 20, 21]  # Valid pre-auth prefixes
    
    data: bytes = field(default_factory=lambda: os.urandom(4))
    channel_prefix: int = -1
    channel_data: bytes = b""
    channel_opened: bool = False
    
    def get_response_type(self, data: bytes) -> str:
        """Get response type from MEP data.
        
        Response formats:
        - Connectionless: [0, mep_data(4), toa_prefix, toa_data...]
        - Channel: [channel_prefix, toa_prefix, toa_data..., hmac(4)?]
        - Broadcast: [1, ...]
        """
        if len(data) == 0:
            return "NOT_VALID"
        
        prefix = data[0]
        
        # Check for connectionless response (prefix 0)
        if prefix == 0:
            if len(data) < 5:
                return "NOT_VALID"
            
            # Check if it's a broadcast (0xFFFFFFFF) or our MEP data
            first_four = data[1:5]
            if first_four == bytes([0xFF, 0xFF, 0xFF, 0xFF]):
                return "CONNECTIONLESS_ID_RESPONSE"
            if first_four == self.data:
                return "CONNECTIONLESS_ID_RESPONSE"
            
            # Unknown MEP data, might be for another client
            _LOGGER.debug("Unknown MEP data in response: %s (expected %s)", 
                         first_four.hex(), self.data.hex())
            return "NOT_VALID"
        
        # Check for broadcast response
        if prefix == 1:
            return "BROADCAST_RESPONSE"
        
        # Check if it's our channel
        if self.channel_opened and prefix == self.channel_prefix:
            return "CID_RESPONSE"
        
        return "NOT_VALID"


class TileVolume:
    """Volume levels for Tile ring commands."""
    LOW = bytes([0x01, 0x01])
    MED = bytes([0x01, 0x02])
    HIGH = bytes([0x01, 0x03])
    AUTO = bytes([0x16, 0x03, 0x03])
    
    @classmethod
    def from_string(cls, volume: str) -> bytes:
        """Convert string volume to bytes."""
        return {
            "low": cls.LOW,
            "med": cls.MED,
            "medium": cls.MED,
            "high": cls.HIGH,
            "auto": cls.AUTO,
        }.get(volume.lower(), cls.MED)


def generate_hmac(secret: bytes, *parts: bytes | int) -> bytes:
    """Generate HMAC-SHA256 for authentication.
    
    Port of CryptoUtils.generateHmac from node-tile:
    - Concatenate all parts into a 32-byte buffer (zero-padded)
    - Create HMAC-SHA256 with the secret key
    """
    data = b""
    for part in parts:
        if isinstance(part, int):
            data += bytes([part])
        elif isinstance(part, bytes):
            data += part
        else:
            data += bytes(part)
    
    # Pad to 32 bytes
    padded = data[:32].ljust(32, b'\x00')
    return hmac.new(secret, padded, hashlib.sha256).digest()


def convert_to_long_buffer(value: int) -> bytes:
    """Convert int to 8-byte little-endian buffer."""
    return struct.pack("<q", value)


class TileAuthenticator:
    """Tile BLE authentication and communication handler.
    
    Implements the full Tile authentication handshake:
    1. TDI sequence - get device info
    2. RandA/RandT exchange - mutual authentication
    3. Channel open - dedicated encrypted channel
    4. HMAC signing for post-auth packets
    """
    
    def __init__(self, client: BleakClient, auth_key_b64: str):
        """Initialize authenticator.
        
        Args:
            client: Connected BleakClient
            auth_key_b64: Base64-encoded auth key from Tile API
        """
        self.client = client
        self.auth_key = base64.b64decode(auth_key_b64)
        
        # Characteristics
        self.mep_command_char: BleakGATTCharacteristic | None = None
        self.mep_response_char: BleakGATTCharacteristic | None = None
        self.tile_id_char: BleakGATTCharacteristic | None = None
        
        # State
        self.toa_processor = ToaProcessor()
        self.mep_processor = ToaMepProcessor()
        
        # Random values for authentication
        self.rand_a: bytes = os.urandom(14)
        self.rand_t: bytes = b""
        self.sres_t: bytes = b""
        
        # Tile info
        self.tile_id: str = ""
        self.tile_id_bytes: bytes = b""
        self.firmware: str = ""
        self.model: str = ""
        self.hardware: str = ""
        
        # Response handling
        self._response_event = asyncio.Event()
        self._response_data: bytes = b""
        self._packet_listeners: dict[int, asyncio.Future] = {}
        
        # Authentication state
        self._authenticated = False
        self._auth_complete_event = asyncio.Event()
    
    @property
    def is_authenticated(self) -> bool:
        """Check if authentication is complete."""
        return self._authenticated
    
    def _on_mep_response(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle MEP response notification."""
        data_bytes = bytes(data)
        _LOGGER.debug("RX MEP: %s", data_bytes.hex())
        
        response_type = self.mep_processor.get_response_type(data_bytes)
        if response_type == "NOT_VALID":
            _LOGGER.debug("Invalid response, ignoring")
            return
        
        # Parse the transaction
        if response_type == "CONNECTIONLESS_ID_RESPONSE":
            # Format: [0, mep_data(4), toa_prefix, toa_data...]
            if len(data_bytes) < 6:
                return
            
            toa_prefix = data_bytes[5]
            toa_data = data_bytes[6:]
            
            _LOGGER.debug("Connectionless response: prefix=%d, data=%s", 
                         toa_prefix, toa_data.hex() if toa_data else "empty")
            
            # Check for waiting listener first
            if toa_prefix in self._packet_listeners:
                fut = self._packet_listeners.pop(toa_prefix)
                if not fut.done():
                    fut.set_result((toa_prefix, toa_data))
                return
            
            # Handle specific connection-less prefixes
            if toa_prefix == ToaPrefix.AUTH_RESPONSE or toa_prefix == ToaPrefix.ASSOCIATE:
                # Auth response: RandT (10 bytes) + SresT (4 bytes)
                self._handle_auth_associate(toa_data)
                # After auth response (21), send RandA again (prefix 16)
                if toa_prefix == ToaPrefix.AUTH_RESPONSE:
                    asyncio.create_task(self._send_rand_a_confirm())
            elif toa_prefix == ToaPrefix.OPEN_CHANNEL:
                # Channel open: channelPrefix, channelData
                self._handle_channel_open(toa_data)
        
        elif response_type == "CID_RESPONSE":
            # Format: [channel_prefix, toa_prefix, toa_data..., hmac(4)?]
            if len(data_bytes) < 2:
                return
            
            toa_prefix = data_bytes[1]
            # Remove channel prefix and HMAC (last 4 bytes if authenticated)
            toa_data = data_bytes[2:-4] if self._authenticated else data_bytes[2:]
            
            _LOGGER.debug("Channel response: prefix=%d, data=%s",
                         toa_prefix, toa_data.hex() if toa_data else "empty")
            
            if toa_prefix == ToaPrefix.READY:
                self._handle_nonce_ready(toa_data)
            elif toa_prefix in self._packet_listeners:
                fut = self._packet_listeners.pop(toa_prefix)
                if not fut.done():
                    fut.set_result((toa_prefix, toa_data))
        
        # Signal any waiters
        self._response_data = data_bytes
        self._response_event.set()
    
    def _handle_auth_associate(self, data: bytes) -> None:
        """Handle authentication associate response."""
        if len(data) >= 14:
            self.rand_t = data[:10]
            self.sres_t = data[10:14]
            _LOGGER.debug("Auth associate: randT=%s, sresT=%s",
                         self.rand_t.hex(), self.sres_t.hex())
    
    def _handle_channel_open(self, data: bytes) -> None:
        """Handle channel open response."""
        if len(data) >= 1:
            self.mep_processor.channel_prefix = data[0]
            self.mep_processor.channel_data = data[1:] if len(data) > 1 else b""
            self.mep_processor.channel_opened = True
            
            _LOGGER.debug("Channel opened: prefix=%d, data=%s",
                         self.mep_processor.channel_prefix,
                         self.mep_processor.channel_data.hex())
            
            # Set TOA processor ready
            self._set_toa_processor_ready()
            
            # Send channel open ACK: [18, 19]
            asyncio.create_task(self._send_channel_ack())
    
    async def _send_channel_ack(self) -> None:
        """Send channel open acknowledgment."""
        await self.send_packets(ToaPrefix.OPEN_CHANNEL, bytes([19]))
    
    def _handle_nonce_ready(self, data: bytes) -> None:
        """Handle nonce ready (READY) response."""
        if len(data) == 0:
            return
        
        self.toa_processor.max_payload_size = data[0]
        nonce_data = data[1:]
        
        if len(nonce_data) >= 7:
            # Features (3 bytes) + nonceB (4 bytes)
            features_info = nonce_data[:3]
            self.toa_processor.nonce_b = struct.unpack("<I", nonce_data[3:7])[0]
            
            if len(nonce_data) > 7:
                features_info = features_info + nonce_data[7:]
            
            self.toa_processor.features_available = features_info
        else:
            self.toa_processor.features_available = nonce_data
        
        self.toa_processor.nonce_t += 1
        self.toa_processor.got_nonce_packet = True
        self._authenticated = True
        self._auth_complete_event.set()
        
        _LOGGER.info("Authentication complete! maxPayload=%d, features=%s, nonceB=%d",
                    self.toa_processor.max_payload_size,
                    self.toa_processor.features_available.hex(),
                    self.toa_processor.nonce_b)
    
    def _set_toa_processor_ready(self) -> None:
        """Set up TOA processor with auth info."""
        self.toa_processor.tile_id = self.tile_id
        self.toa_processor.firmware = self.firmware
        self.toa_processor.model = self.model
        self.toa_processor.auth_key_hmac = self._get_auth_key_hmac()
        self.toa_processor.security_level = 1
        self.toa_processor.got_nonce_packet = True
    
    def _get_auth_key_hmac(self) -> bytes:
        """Generate the auth key HMAC for packet signing."""
        return generate_hmac(
            self.auth_key,
            self.rand_a,
            self.mep_processor.channel_data,
            self.mep_processor.channel_prefix,
            self.mep_processor.data
        )[:16]
    
    async def discover_characteristics(self) -> bool:
        """Discover required BLE characteristics."""
        for service in self.client.services:
            svc_uuid = str(service.uuid).lower()
            if "feed" in svc_uuid or FEED_SERVICE_UUID.lower() == svc_uuid:
                _LOGGER.debug("Found FEED service: %s", service.uuid)
                
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    if MEP_COMMAND_CHAR_UUID.lower() == char_uuid:
                        self.mep_command_char = char
                    elif MEP_RESPONSE_CHAR_UUID.lower() == char_uuid:
                        self.mep_response_char = char
                    elif TILE_ID_CHAR_UUID.lower() == char_uuid:
                        self.tile_id_char = char
        
        if not self.mep_command_char or not self.mep_response_char:
            _LOGGER.error("Required characteristics not found")
            return False
        
        _LOGGER.debug("Found MEP command and response characteristics")
        return True
    
    async def subscribe_notifications(self) -> None:
        """Subscribe to MEP response notifications."""
        if self.mep_response_char:
            await self.client.start_notify(
                self.mep_response_char, self._on_mep_response
            )
            _LOGGER.debug("Subscribed to MEP response notifications")
    
    async def send_packets_pre_auth(self, toa_prefix: int, toa_data: bytes) -> bytes:
        """Send pre-authentication packet.
        
        Format: [0, mep_data(4), toa_prefix, toa_data...]
        """
        if toa_prefix not in ToaMepProcessor.MAGIC_PREFIX_BYTES:
            raise ValueError(f"Invalid prefix {toa_prefix} for pre-auth")
        
        packet = bytes([0]) + self.mep_processor.data + bytes([toa_prefix]) + toa_data
        _LOGGER.debug("TX pre-auth: %s", packet.hex())
        
        # Tile MEP command characteristic uses write-without-response
        await self.client.write_gatt_char(
            self.mep_command_char, packet, response=False
        )
        
        return packet
    
    async def send_packet_pre_auth_async(
        self, 
        toa_prefix: int, 
        toa_data: bytes,
        response_prefix: int,
        timeout: float = 5.0
    ) -> tuple[int, bytes]:
        """Send pre-auth packet and wait for response.
        
        Args:
            toa_prefix: The request prefix to send
            toa_data: The data to send
            response_prefix: The response prefix to wait for
            timeout: Timeout in seconds
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._packet_listeners[response_prefix] = fut
        
        await self.send_packets_pre_auth(toa_prefix, toa_data)
        
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._packet_listeners.pop(response_prefix, None)
            raise
    
    async def send_packets(self, toa_prefix: int, toa_data: bytes) -> bytes:
        """Send authenticated packet with HMAC.
        
        Format: [channel_prefix, toa_prefix, toa_data..., hmac(4)]
        """
        payload = bytes([toa_prefix]) + toa_data
        
        self.toa_processor.nonce_a += 1
        
        # Generate HMAC if authenticated
        if self.toa_processor.got_nonce_packet:
            nonce_a_buf = convert_to_long_buffer(self.toa_processor.nonce_a)
            packet_hmac = generate_hmac(
                self.toa_processor.auth_key_hmac,
                nonce_a_buf,
                1,  # direction
                len(payload),
                payload
            )[:4]
            payload = payload + packet_hmac
        
        # Add channel prefix
        packet = bytes([self.mep_processor.channel_prefix]) + payload
        
        _LOGGER.debug("TX auth: %s", packet.hex())
        
        # Tile MEP command characteristic uses write-without-response
        await self.client.write_gatt_char(
            self.mep_command_char, packet, response=False
        )
        
        return packet
    
    async def send_packets_async(
        self,
        toa_prefix: int,
        toa_data: bytes,
        response_prefix: int,
        timeout: float = 5.0
    ) -> tuple[int, bytes]:
        """Send authenticated packet and wait for response."""
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._packet_listeners[response_prefix] = fut
        
        await self.send_packets(toa_prefix, toa_data)
        
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._packet_listeners.pop(response_prefix, None)
            raise
    
    async def start_tdi_sequence(self) -> bool:
        """Start TDI sequence to get Tile info.
        
        Request: TILE_ID, FIRMWARE, MODEL, HARDWARE
        """
        _LOGGER.info("Starting TDI sequence...")
        
        try:
            # Request features first (prefix 19 -> response 20)
            prefix, data = await self.send_packet_pre_auth_async(
                ToaPrefix.TDI_REQUEST, bytes([TdiRequest.FEATURES]),
                ToaPrefix.TDI_RESPONSE
            )
            
            if prefix == 32:  # Error prefix
                _LOGGER.error("TDI error response")
                return False
            
            _LOGGER.debug("TDI features response: %s", data.hex() if data else "empty")
            
            # Check available features and request each
            available = data[0] if data else 0
            
            # Request TILE_ID (bit 0)
            if available & (1 << 0):
                prefix, data = await self.send_packet_pre_auth_async(
                    ToaPrefix.TDI_REQUEST, bytes([TdiRequest.TILE_ID]),
                    ToaPrefix.TDI_RESPONSE
                )
                self.tile_id = data.hex()
                self.tile_id_bytes = data
                _LOGGER.debug("Tile ID: %s", self.tile_id)
            
            # Request FIRMWARE (bit 1)
            if available & (1 << 1):
                prefix, data = await self.send_packet_pre_auth_async(
                    ToaPrefix.TDI_REQUEST, bytes([TdiRequest.FIRMWARE]),
                    ToaPrefix.TDI_RESPONSE
                )
                self.firmware = data.decode("utf-8", errors="replace")
                _LOGGER.debug("Firmware: %s", self.firmware)
            
            # Request MODEL (bit 2)
            if available & (1 << 2):
                prefix, data = await self.send_packet_pre_auth_async(
                    ToaPrefix.TDI_REQUEST, bytes([TdiRequest.MODEL]),
                    ToaPrefix.TDI_RESPONSE
                )
                self.model = data.decode("utf-8", errors="replace")
                _LOGGER.debug("Model: %s", self.model)
            
            # Request HARDWARE (bit 3)
            if available & (1 << 3):
                prefix, data = await self.send_packet_pre_auth_async(
                    ToaPrefix.TDI_REQUEST, bytes([TdiRequest.HARDWARE]),
                    ToaPrefix.TDI_RESPONSE
                )
                self.hardware = data.decode("utf-8", errors="replace")
                _LOGGER.debug("Hardware: %s", self.hardware)
            
            _LOGGER.info("TDI complete: id=%s, fw=%s, model=%s, hw=%s",
                        self.tile_id, self.firmware, self.model, self.hardware)
            
            return True
            
        except asyncio.TimeoutError:
            _LOGGER.error("TDI sequence timeout")
            return False
        except Exception as e:
            _LOGGER.error("TDI sequence error: %s", e)
            return False
    
    async def send_rand_a(self) -> None:
        """Send RandA to start authentication.
        
        RandA is sent with prefix 20. Response comes as prefix 21 (AUTH) or 27 (ASSOCIATE).
        """
        _LOGGER.debug("Sending RandA: %s", self.rand_a.hex())
        # Use prefix 20 for sending RandA
        await self.send_packets_pre_auth(20, self.rand_a)
    
    async def _send_rand_a_confirm(self) -> None:
        """Send RandA confirmation after receiving auth response.
        
        This is sent with prefix 16 (TEST) after receiving prefix 21 (AUTH_RESPONSE).
        """
        _LOGGER.debug("Sending RandA confirm: %s", self.rand_a.hex())
        await self.send_packets_pre_auth(16, self.rand_a)
    
    async def authenticate(self, timeout: float = 10.0) -> bool:
        """Perform full authentication sequence.
        
        1. Discover characteristics
        2. Subscribe to notifications
        3. Run TDI sequence
        4. Send RandA
        5. Wait for auth complete
        """
        try:
            # Step 1: Discover characteristics
            if not await self.discover_characteristics():
                return False
            
            # Step 2: Subscribe to notifications
            await self.subscribe_notifications()
            
            # Give a moment for subscription to be ready
            await asyncio.sleep(0.1)
            
            # Step 3: TDI sequence
            if not await self.start_tdi_sequence():
                _LOGGER.warning("TDI sequence failed, trying auth anyway...")
            
            # Step 4: Send RandA
            await self.send_rand_a()
            
            # Step 5: Wait for auth complete
            try:
                await asyncio.wait_for(
                    self._auth_complete_event.wait(), 
                    timeout=timeout
                )
                return True
            except asyncio.TimeoutError:
                _LOGGER.error("Authentication timeout - no READY response")
                return False
                
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", e)
            return False
    
    async def send_ring(
        self,
        volume: bytes = None,
        duration: int = 5,
        song_id: int = 0
    ) -> bool:
        """Send ring command to Tile.
        
        Args:
            volume: Volume bytes (use TileVolume constants)
            duration: Ring duration in seconds (1-30)
            song_id: Optional song ID to play
        """
        if not self._authenticated:
            _LOGGER.error("Cannot ring - not authenticated")
            return False
        
        if volume is None:
            volume = TileVolume.MED
        
        duration = max(1, min(duration, 30))
        
        # Build ring payload
        # SongCommand.PLAY = 2, then volume bytes, then duration
        payload = bytes([SongCommand.PLAY]) + volume + bytes([duration])
        
        if song_id > 0:
            payload = bytes([song_id]) + payload
        
        _LOGGER.info("Sending ring: volume=%s, duration=%d, song=%d",
                    volume.hex(), duration, song_id)
        
        try:
            # TOA prefix 5 = Song, expect response prefix 7
            prefix, data = await self.send_packets_async(
                5,  # Song prefix
                payload,
                7,  # Song response
                timeout=5.0
            )
            
            _LOGGER.debug("Ring response: prefix=%d, data=%s", prefix, data.hex())
            
            # Check for success (response type 2 = PLAY_OK)
            if len(data) > 0 and data[0] == 2:
                _LOGGER.info("Ring acknowledged!")
                return True
            
            return True  # Assume success if we got a response
            
        except asyncio.TimeoutError:
            _LOGGER.warning("Ring command timeout (may still be playing)")
            return True  # Ring might still work even without response
        except Exception as e:
            _LOGGER.error("Ring error: %s", e)
            return False


async def connect_and_authenticate(
    device: BLEDevice,
    auth_key_b64: str,
    timeout: float = 20.0
) -> TileAuthenticator | None:
    """Connect to a Tile and authenticate.
    
    Args:
        device: BLE device to connect to
        auth_key_b64: Base64-encoded auth key from Tile API
        timeout: Connection timeout in seconds
    
    Returns:
        Authenticated TileAuthenticator, or None on failure
    """
    try:
        client = BleakClient(device, timeout=timeout)
        await client.connect()
        
        if not client.is_connected:
            _LOGGER.error("Failed to connect to %s", device.address)
            return None
        
        _LOGGER.info("Connected to %s", device.address)
        
        auth = TileAuthenticator(client, auth_key_b64)
        
        if await auth.authenticate():
            return auth
        
        await client.disconnect()
        return None
        
    except Exception as e:
        _LOGGER.error("Connection error: %s", e)
        return None
