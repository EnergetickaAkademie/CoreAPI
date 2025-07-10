#!/usr/bin/env python3
"""
Binary Protocol for ESP32 Board Communication
Optimized for low memory usage and efficient data transmission.
"""

import struct
import time
from typing import Optional, Tuple, Dict, Any

# Protocol constants
MAX_BOARD_NAME_LENGTH = 32
MAX_BOARD_TYPE_LENGTH = 16
MAX_STRING_LENGTH = 64
MAX_BUILDING_TABLE_ENTRIES = 255  # Maximum number of building types

# Data type flags
DATA_TYPE_GENERATION = 0x01
DATA_TYPE_CONSUMPTION = 0x02
DATA_TYPE_BOTH = 0x03

# Round type flags
ROUND_TYPE_DAY = 0x01
ROUND_TYPE_NIGHT = 0x00

# Status flags for poll response
STATUS_FLAG_ROUND_TYPE = 0x01  # Bit 0: Round type (0=night, 1=day)
STATUS_FLAG_GAME_ACTIVE = 0x02  # Bit 1: Game active
STATUS_FLAG_EXPECTING_DATA = 0x04  # Bit 2: Expecting data
STATUS_FLAG_TABLE_UPDATED = 0x08  # Bit 3: Building table updated

# Protocol version
PROTOCOL_VERSION = 0x01

class BinaryProtocolError(Exception):
    """Custom exception for binary protocol errors"""
    pass

class BoardBinaryProtocol:
    """Handles binary protocol for board communication"""
    
    @staticmethod
    def validate_string_length(data: bytes, max_length: int) -> bool:
        """Validate string length to prevent overflows"""
        return len(data) <= max_length
    
    @staticmethod
    def pack_string(text: str, max_length: int) -> bytes:
        """Pack string with length validation"""
        text_bytes = text.encode('utf-8')[:max_length-1]  # Reserve 1 byte for null terminator
        return text_bytes.ljust(max_length, b'\x00')
    
    @staticmethod
    def unpack_string(data: bytes) -> str:
        """Unpack null-terminated string"""
        null_pos = data.find(b'\x00')
        if null_pos >= 0:
            return data[:null_pos].decode('utf-8', errors='ignore')
        return data.decode('utf-8', errors='ignore')
    
    @staticmethod
    def pack_registration_request(board_id: int, board_name: str, board_type: str) -> bytes:
        """
        Pack board registration request
        Format: version(1) + board_id(4) + board_name(32) + board_type(16) = 53 bytes
        """
        if board_id < 0 or board_id > 0xFFFFFFFF:
            raise BinaryProtocolError("Board ID must be a 32-bit unsigned integer")
        
        version = struct.pack('B', PROTOCOL_VERSION)
        board_id_bytes = struct.pack('>I', board_id)
        board_name_bytes = BoardBinaryProtocol.pack_string(board_name, MAX_BOARD_NAME_LENGTH)
        board_type_bytes = BoardBinaryProtocol.pack_string(board_type, MAX_BOARD_TYPE_LENGTH)
        
        return version + board_id_bytes + board_name_bytes + board_type_bytes
    
    @staticmethod
    def unpack_registration_request(data: bytes) -> Tuple[int, str, str]:
        """
        Unpack board registration request
        Returns: (board_id, board_name, board_type)
        """
        if len(data) < 53:
            raise BinaryProtocolError(f"Registration data too short: {len(data)} bytes, expected 53")
        
        version = struct.unpack('B', data[0:1])[0]
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        board_id = struct.unpack('>I', data[1:5])[0]
        board_name = BoardBinaryProtocol.unpack_string(data[5:37])
        board_type = BoardBinaryProtocol.unpack_string(data[37:53])
        
        return board_id, board_name, board_type
    
    @staticmethod
    def pack_power_data(board_id: int, generation: Optional[float], consumption: Optional[float], 
                       timestamp: Optional[int] = None) -> bytes:
        """
        Pack power data submission
        Format: version(1) + board_id(4) + timestamp(8) + generation(4) + consumption(4) + flags(1) = 22 bytes
        Power values are in watts * 100 (2 decimal places precision, stored as 32-bit signed int)
        """
        if board_id < 0 or board_id > 0xFFFFFFFF:
            raise BinaryProtocolError("Board ID must be a 32-bit unsigned integer")
        
        if timestamp is None:
            timestamp = int(time.time())
        
        # Validate timestamp (64-bit Unix timestamp)
        if timestamp < 0 or timestamp > 0x7FFFFFFFFFFFFFFF:
            raise BinaryProtocolError("Invalid Unix timestamp")
        
        # Convert power values to integers (watts * 100 for 2 decimal precision)
        gen_int = int(generation * 100) if generation is not None else 0x7FFFFFFF  # Use max int as null
        cons_int = int(consumption * 100) if consumption is not None else 0x7FFFFFFF
        
        # Validate power values don't overflow
        if abs(gen_int) > 0x7FFFFFFE:  # Reserve max int for null
            raise BinaryProtocolError("Generation value too large")
        if abs(cons_int) > 0x7FFFFFFE:
            raise BinaryProtocolError("Consumption value too large")
        
        # Set data type flags
        flags = 0
        if generation is not None:
            flags |= DATA_TYPE_GENERATION
        if consumption is not None:
            flags |= DATA_TYPE_CONSUMPTION
        
        return struct.pack('>BIQiiB', PROTOCOL_VERSION, board_id, timestamp, gen_int, cons_int, flags)
    
    @staticmethod
    def unpack_power_data(data: bytes) -> Tuple[int, Optional[float], Optional[float], int]:
        """
        Unpack power data submission
        Returns: (board_id, generation, consumption, timestamp)
        """
        if len(data) < 22:
            raise BinaryProtocolError(f"Power data too short: {len(data)} bytes, expected 22")
        
        version, board_id, timestamp, gen_int, cons_int, flags = struct.unpack('>BIQiiB', data[:22])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        # Convert back from integers, handle null values
        generation = None if gen_int == 0x7FFFFFFF else gen_int / 100.0
        consumption = None if cons_int == 0x7FFFFFFF else cons_int / 100.0
        
        # Apply flags (only return values that were actually sent)
        if not (flags & DATA_TYPE_GENERATION):
            generation = None
        if not (flags & DATA_TYPE_CONSUMPTION):
            consumption = None
        
        return board_id, generation, consumption, timestamp
    
    @staticmethod
    def pack_poll_response(round_num: int, score: int, generation: Optional[float], 
                          consumption: Optional[float], round_type: str, 
                          game_active: bool, expecting_data: bool, building_table_version: int,
                          timestamp: Optional[int] = None) -> bytes:
        """
        Pack poll response for ESP32
        Format: version(1) + timestamp(8) + round(2) + score(4) + generation(4) + consumption(4) + table_version(8) + flags(1) = 32 bytes
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        # Validate inputs
        if round_num < 0 or round_num > 65535:
            raise BinaryProtocolError("Round number must fit in 16 bits")
        if score < 0 or score > 0xFFFFFFFF:
            raise BinaryProtocolError("Score must fit in 32 bits")
        
        # Convert power values
        gen_int = int(generation * 100) if generation is not None else 0x7FFFFFFF
        cons_int = int(consumption * 100) if consumption is not None else 0x7FFFFFFF
        
        # Pack flags: bit 0 = round_type, bit 1 = game_active, bit 2 = expecting_data
        flags = 0
        if round_type == 'day':
            flags |= STATUS_FLAG_ROUND_TYPE
        if game_active:
            flags |= STATUS_FLAG_GAME_ACTIVE
        if expecting_data:
            flags |= STATUS_FLAG_EXPECTING_DATA
        
        return struct.pack('>BQHIiiQB', PROTOCOL_VERSION, timestamp, round_num, score, gen_int, cons_int, building_table_version, flags)
    
    @staticmethod
    def unpack_poll_response(data: bytes) -> Dict[str, Any]:
        """
        Unpack poll response
        Returns: Dictionary with status information
        """
        if len(data) < 32:
            raise BinaryProtocolError(f"Poll response too short: {len(data)} bytes, expected 32")
        
        version, timestamp, round_num, score, gen_int, cons_int, building_table_version, flags = struct.unpack('>BQHIiiQB', data[:32])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        # Convert back from integers
        generation = None if gen_int == 0x7FFFFFFF else gen_int / 100.0
        consumption = None if cons_int == 0x7FFFFFFF else cons_int / 100.0
        
        # Unpack flags
        round_type = 'day' if (flags & STATUS_FLAG_ROUND_TYPE) else 'night'
        game_active = bool(flags & STATUS_FLAG_GAME_ACTIVE)
        expecting_data = bool(flags & STATUS_FLAG_EXPECTING_DATA)
        
        return {
            'timestamp': timestamp,
            'round': round_num,
            'score': score,
            'generation': generation,
            'consumption': consumption,
            'round_type': round_type,
            'game_active': game_active,
            'expecting_data': expecting_data,
            'building_table_version': building_table_version
        }
    
    @staticmethod
    def pack_registration_response(success: bool, message: str = "") -> bytes:
        """
        Pack registration response
        Format: version(1) + success(1) + message_length(1) + message(N) = 3+N bytes (max 67 bytes)
        """
        message_bytes = message.encode('utf-8')[:MAX_STRING_LENGTH]
        if len(message_bytes) > 255:
            raise BinaryProtocolError("Message too long")
        
        success_byte = 0x01 if success else 0x00
        message_length = len(message_bytes)
        
        return struct.pack('>BBB', PROTOCOL_VERSION, success_byte, message_length) + message_bytes
    
    @staticmethod
    def unpack_registration_response(data: bytes) -> Tuple[bool, str]:
        """
        Unpack registration response
        Returns: (success, message)
        """
        if len(data) < 3:
            raise BinaryProtocolError(f"Registration response too short: {len(data)} bytes, expected at least 3")
        
        version, success_byte, message_length = struct.unpack('>BBB', data[:3])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        if len(data) < 3 + message_length:
            raise BinaryProtocolError(f"Message length mismatch: expected {message_length}, got {len(data) - 3}")
        
        success = bool(success_byte)
        message = data[3:3+message_length].decode('utf-8')
        
        return success, message
    
    @staticmethod
    def pack_building_table_request(board_id: int) -> bytes:
        """
        Pack building table request
        Format: version(1) + board_id(4) = 5 bytes
        """
        if board_id < 0 or board_id > 0xFFFFFFFF:
            raise BinaryProtocolError("Board ID must be a 32-bit unsigned integer")
        
        return struct.pack('>BI', PROTOCOL_VERSION, board_id)
    
    @staticmethod
    def unpack_building_table_request(data: bytes) -> int:
        """
        Unpack building table request
        Returns: board_id
        """
        if len(data) < 5:
            raise BinaryProtocolError(f"Building table request too short: {len(data)} bytes, expected 5")
        
        version, board_id = struct.unpack('>BI', data[:5])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        return board_id
    
    @staticmethod
    def pack_building_table_response(success: bool, table: Optional[Dict[int, Tuple[str, int]]]) -> bytes:
        """
        Pack building table response
        Format: version(1) + success(1) + entries(1) + table(N) = 3 + N*5 bytes
        Each entry: building_id(4) + building_type(1) = 5 bytes
        """
        if table is None:
            table = {}
        
        if len(table) > MAX_BUILDING_TABLE_ENTRIES:
            raise BinaryProtocolError(f"Too many building table entries: {len(table)}, max allowed: {MAX_BUILDING_TABLE_ENTRIES}")
        
        success_byte = 0x01 if success else 0x00
        entries = len(table)
        
        # Pack table entries
        table_data = b''.join(struct.pack('>IB', building_id, building_type) for building_id, (building_type, _) in table.items())
        
        return struct.pack('>BBH', PROTOCOL_VERSION, success_byte, entries) + table_data
    
    @staticmethod
    def unpack_building_table_response(data: bytes) -> Tuple[bool, Dict[int, Tuple[str, int]]]:
        """
        Unpack building table response
        Returns: (success, table)
        """
        if len(data) < 3:
            raise BinaryProtocolError(f"Building table response too short: {len(data)} bytes, expected at least 3")
        
        version, success_byte, entries = struct.unpack('>BBH', data[:4])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        success = bool(success_byte)
        table = {}
        
        # Unpack each table entry
        pos = 4
        for _ in range(entries):
            if len(data) < pos + 5:
                raise BinaryProtocolError("Building table response length mismatch")
            building_id, building_type = struct.unpack('>IB', data[pos:pos+5])
            table[building_id] = (building_type, )
            pos += 5
        
        return success, table
    
    @staticmethod
    def pack_building_table(table: Dict[int, int], version: int) -> bytes:
        """
        Pack building consumption table for download
        Format: version(1) + table_version(8) + entry_count(1) + entries[count](type(1) + consumption(4))
        Maximum size: 1 + 8 + 1 + (255 * 5) = 1285 bytes
        """
        if not (0 <= len(table) <= MAX_BUILDING_TABLE_ENTRIES):
            raise BinaryProtocolError(f"Too many building table entries: {len(table)}, max {MAX_BUILDING_TABLE_ENTRIES}")
        
        # Validate table entries
        for building_type, consumption in table.items():
            if not (0 <= building_type <= 255):
                raise BinaryProtocolError(f"Building type must be uint8: {building_type}")
            if not (-2147483648 <= consumption <= 2147483647):
                raise BinaryProtocolError(f"Consumption must be int32: {consumption}")
        
        # Pack header: version + table_version + entry_count
        data = struct.pack('>BQB', PROTOCOL_VERSION, version, len(table))
        
        # Pack entries: type(1) + consumption(4) for each entry
        for building_type, consumption in sorted(table.items()):
            data += struct.pack('>Bi', building_type, consumption)
        
        return data
    
    @staticmethod
    def unpack_building_table(data: bytes) -> Tuple[Dict[int, int], int]:
        """
        Unpack building consumption table
        Returns: (table, version)
        """
        if len(data) < 10:  # Minimum: version(1) + table_version(8) + entry_count(1)
            raise BinaryProtocolError(f"Building table too short: {len(data)} bytes, expected at least 10")
        
        version, table_version, entry_count = struct.unpack('>BQB', data[:10])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        expected_size = 10 + (entry_count * 5)  # Each entry is 5 bytes: type(1) + consumption(4)
        if len(data) != expected_size:
            raise BinaryProtocolError(f"Building table size mismatch: expected {expected_size}, got {len(data)}")
        
        table = {}
        offset = 10
        
        for i in range(entry_count):
            building_type, consumption = struct.unpack('>Bi', data[offset:offset+5])
            table[building_type] = consumption
            offset += 5
        
        return table, table_version
