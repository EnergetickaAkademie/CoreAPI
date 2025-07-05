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

# Data type flags
DATA_TYPE_GENERATION = 0x01
DATA_TYPE_CONSUMPTION = 0x02
DATA_TYPE_BOTH = 0x03

# Round type flags
ROUND_TYPE_DAY = 0x01
ROUND_TYPE_NIGHT = 0x00

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
                          game_active: bool, expecting_data: bool, timestamp: Optional[int] = None) -> bytes:
        """
        Pack poll response for ESP32
        Format: version(1) + timestamp(8) + round(2) + score(4) + generation(4) + consumption(4) + flags(1) = 24 bytes
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
            flags |= 0x01
        if game_active:
            flags |= 0x02
        if expecting_data:
            flags |= 0x04
        
        return struct.pack('>BQHIiiB', PROTOCOL_VERSION, timestamp, round_num, score, gen_int, cons_int, flags)
    
    @staticmethod
    def unpack_poll_response(data: bytes) -> Dict[str, Any]:
        """
        Unpack poll response
        Returns: Dictionary with status information
        """
        if len(data) < 24:
            raise BinaryProtocolError(f"Poll response too short: {len(data)} bytes, expected 24")
        
        version, timestamp, round_num, score, gen_int, cons_int, flags = struct.unpack('>BQHIiiB', data[:24])
        
        if version != PROTOCOL_VERSION:
            raise BinaryProtocolError(f"Unsupported protocol version: {version}")
        
        # Convert back from integers
        generation = None if gen_int == 0x7FFFFFFF else gen_int / 100.0
        consumption = None if cons_int == 0x7FFFFFFF else cons_int / 100.0
        
        # Unpack flags
        round_type = 'day' if (flags & 0x01) else 'night'
        game_active = bool(flags & 0x02)
        expecting_data = bool(flags & 0x04)
        
        return {
            'timestamp': timestamp,
            'round': round_num,
            'score': score,
            'generation': generation,
            'consumption': consumption,
            'round_type': round_type,
            'game_active': game_active,
            'expecting_data': expecting_data
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
            raise BinaryProtocolError("Message length mismatch")
        
        success = bool(success_byte)
        message = data[3:3+message_length].decode('utf-8', errors='ignore')
        
        return success, message
