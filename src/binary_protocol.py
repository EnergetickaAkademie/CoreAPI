#!/usr/bin/env python3
"""
Binary Protocol for ESP32 Board Communication
Optimized binary data format for efficient communication with ESP32 boards
"""

import struct
from typing import Tuple, Dict, List, Any, Optional
from enum import IntEnum

# Protocol constants
MAX_BOARD_NAME_LENGTH = 32
MAX_BOARD_TYPE_LENGTH = 16
MAX_STRING_LENGTH = 64
MAX_BUILDING_TABLE_ENTRIES = 64

class BinaryProtocolError(Exception):
    """Custom exception for binary protocol errors"""
    pass

class BoardBinaryProtocol:
    """
    Binary protocol implementation for ESP32 board communication
    Handles packing and unpacking of binary data for efficient communication
    """
    
    @staticmethod
    def pack_string(text: str, max_length: int) -> bytes:
        """Pack a string into a fixed-length byte array with null padding"""
        encoded = text.encode('utf-8')[:max_length]
        return encoded.ljust(max_length, b'\x00')
    
    @staticmethod
    def unpack_string(data: bytes) -> str:
        """Unpack a null-terminated string from bytes"""
        return data.rstrip(b'\x00').decode('utf-8', errors='ignore')
    
    @staticmethod
    def pack_registration_request(board_id: int, board_name: str, board_type: str) -> bytes:
        """
        Pack board registration request
        Format: board_id(4) + board_name(32) + board_type(16) = 52 bytes
        """
        data = struct.pack('>I', board_id)
        data += BoardBinaryProtocol.pack_string(board_name, MAX_BOARD_NAME_LENGTH)
        data += BoardBinaryProtocol.pack_string(board_type, MAX_BOARD_TYPE_LENGTH)
        return data
    
    @staticmethod
    def unpack_registration_request(data: bytes) -> Tuple[int, str, str]:
        """
        Unpack board registration request without protocol version
        Format: board_id(4) + board_name(32) + board_type(16) = 52 bytes
        Returns: (board_id, board_name, board_type)
        """
        if len(data) < 52:
            raise BinaryProtocolError(f"Invalid registration data length: {len(data)}, expected at least 52 bytes")
        
        board_id = struct.unpack('>I', data[0:4])[0]
        
        return board_id
    
    @staticmethod
    def pack_registration_response(success: bool, message: str) -> bytes:
        """
        Pack registration response
        Format: success(1) + message_len(1) + message
        """
        success_byte = b'\x01' if success else b'\x00'
        message_bytes = message.encode('utf-8')[:255]
        message_len = len(message_bytes)
        
        return success_byte + struct.pack('B', message_len) + message_bytes
    
    @staticmethod
    def unpack_registration_response(data: bytes) -> Tuple[bool, str]:
        """Unpack registration response"""
        if len(data) < 2:
            raise BinaryProtocolError("Invalid response data")
        
        success = data[0] != 0
        message_len = data[1]
        
        if len(data) < 2 + message_len:
            raise BinaryProtocolError("Invalid response message length")
        
        message = data[2:2+message_len].decode('utf-8', errors='ignore')
        return success, message
    
    @staticmethod
    def pack_coefficients_response(production_coeffs: Dict, consumption_coeffs: Dict) -> bytes:
        """
        Pack production and consumption coefficients
        Format: prod_count(1) + [source_id(1) + coeff(4)]* + cons_count(1) + [building_id(1) + consumption(4)]*
        Uses signed integers for production to support negative values (e.g., battery charging)
        """
        data = b''
        
        # Pack production coefficients (using signed integers)
        prod_count = len(production_coeffs)
        data += struct.pack('B', prod_count)
        
        for source, coeff in production_coeffs.items():
            source_id = source.value if hasattr(source, 'value') else int(source)
            coeff_int = int(coeff * 1000)  # Convert to mW (signed)
            data += struct.pack('>Bi', source_id, coeff_int)
        
        # Pack consumption coefficients  
        cons_count = len(consumption_coeffs)
        data += struct.pack('B', cons_count)
        
        for building, consumption in consumption_coeffs.items():
            building_id = building.value if hasattr(building, 'value') else int(building)
            cons_int = int(consumption * 1000) if consumption else 0  # Convert to mW
            data += struct.pack('>Bi', building_id, cons_int)
        
        return data
    
    @staticmethod
    def pack_production_values(prod_coeffs: Dict) -> bytes:
        """
        Pack production coefficient values
        Format: count(1) + [source_id(1) + coeff(4)]*
        Uses signed integers to support negative coefficients (e.g., battery charging)
        """
        data = b''
        count = len(prod_coeffs)
        data += struct.pack('B', count)
        
        for source, coeff in prod_coeffs.items():
            source_id = source.value if hasattr(source, 'value') else int(source)
            coeff_int = int(coeff * 1000)  # Convert to mW (signed)
            data += struct.pack('>Bi', source_id, coeff_int)
        
        return data
    
    @staticmethod
    def pack_production_ranges(prod_ranges: Dict) -> bytes:
        """
        Pack production range values (min, max) for power plants
        Format: count(1) + [source_id(1) + min_power(4) + max_power(4)]*
        Uses signed integers to support negative values (e.g., battery charging)
        """
        data = b''
        count = len(prod_ranges)
        data += struct.pack('B', count)
        
        for source, (min_power, max_power) in prod_ranges.items():
            source_id = source.value if hasattr(source, 'value') else int(source)
            min_power_mw = int(min_power * 1000)  # Convert to mW (signed)
            max_power_mw = int(max_power * 1000)  # Convert to mW (signed)
            data += struct.pack('>Bii', source_id, min_power_mw, max_power_mw)
        
        return data
    
    @staticmethod
    def pack_consumption_values(cons_coeffs: Dict) -> bytes:
        """
        Pack consumption coefficient values
        Format: count(1) + [building_id(1) + consumption(4)]*
        """
        data = b''
        count = len(cons_coeffs)
        data += struct.pack('B', count)
        
        for building, consumption in cons_coeffs.items():
            building_id = building.value if hasattr(building, 'value') else int(building)
            cons_int = int(consumption * 1000) if consumption else 0  # Convert to mW
            data += struct.pack('>Bi', building_id, cons_int)
        
        return data
    
    @staticmethod
    def unpack_power_values(data: bytes) -> Tuple[float, float]:
        """
        Unpack power values from ESP32
        Format: production(4) + consumption(4) = 8 bytes
        Returns: (production_W, consumption_W)
        """
        if len(data) < 8:
            raise BinaryProtocolError(f"Invalid power data length: {len(data)}, expected 8 bytes")
        
        prod_mw, cons_mw = struct.unpack('>ii', data[:8])
        
        # Convert from mW to W
        production = prod_mw / 1000.0
        consumption = cons_mw / 1000.0
        
        return production, consumption
    
    @staticmethod
    def pack_power_data(production: float, consumption: float) -> bytes:
        """
        Pack power data for transmission
        Format: production(4) + consumption(4) = 8 bytes
        """
        prod_mw = int(production * 1000)  # Convert to mW
        cons_mw = int(consumption * 1000)  # Convert to mW
        
        return struct.pack('>ii', prod_mw, cons_mw)
    
    @staticmethod
    def pack_building_table(table: Dict[int, int], version: int) -> bytes:
        """
        Pack building consumption table
        Format: version(4) + count(1) + [building_type(1) + consumption(4)]*
        """
        data = struct.pack('>I', version)
        data += struct.pack('B', len(table))
        
        for building_type, consumption in table.items():
            data += struct.pack('>Bi', building_type, consumption)
        
        return data
    
    @staticmethod
    def unpack_building_table(data: bytes) -> Tuple[Dict[int, int], int]:
        """
        Unpack building consumption table
        Returns: (table_dict, version)
        """
        if len(data) < 5:
            raise BinaryProtocolError("Invalid building table data")
        
        version = struct.unpack('>I', data[:4])[0]
        count = data[4]
        
        table = {}
        offset = 5
        
        for i in range(count):
            if offset + 5 > len(data):
                raise BinaryProtocolError("Invalid building table entry")
            
            building_type, consumption = struct.unpack('>Bi', data[offset:offset+5])
            table[building_type] = consumption
            offset += 5
        
        return table, version
    
    @staticmethod
    def pack_game_status(current_round: int, total_rounds: int, round_type: str, 
                        expecting_data: bool) -> bytes:
        """
        Pack game status for board polling
        Format: current_round(2) + total_rounds(2) + round_type_len(1) + round_type + expecting_data(1)
        """
        data = struct.pack('>HH', current_round, total_rounds)
        
        round_type_bytes = round_type.encode('utf-8')[:255]
        data += struct.pack('B', len(round_type_bytes))
        data += round_type_bytes
        data += struct.pack('B', 1 if expecting_data else 0)
        
        return data
    
    @staticmethod
    def unpack_game_status(data: bytes) -> Tuple[int, int, str, bool]:
        """
        Unpack game status from poll response
        Returns: (current_round, total_rounds, round_type, expecting_data)
        """
        if len(data) < 6:
            raise BinaryProtocolError("Invalid game status data")
        
        current_round, total_rounds = struct.unpack('>HH', data[:4])
        round_type_len = data[4]
        
        if len(data) < 6 + round_type_len:
            raise BinaryProtocolError("Invalid round type length")
        
        round_type = data[5:5+round_type_len].decode('utf-8', errors='ignore')
        expecting_data = data[5+round_type_len] != 0
        
        return current_round, total_rounds, round_type, expecting_data

# Utility functions for common binary operations
def pack_uint32(value: int) -> bytes:
    """Pack a 32-bit unsigned integer in big-endian format"""
    return struct.pack('>I', value)

def unpack_uint32(data: bytes, offset: int = 0) -> int:
    """Unpack a 32-bit unsigned integer from big-endian format"""
    return struct.unpack('>I', data[offset:offset+4])[0]

def pack_int32(value: int) -> bytes:
    """Pack a 32-bit signed integer in big-endian format"""
    return struct.pack('>i', value)

def unpack_int32(data: bytes, offset: int = 0) -> int:
    """Unpack a 32-bit signed integer from big-endian format"""
    return struct.unpack('>i', data[offset:offset+4])[0]

def pack_float(value: float) -> bytes:
    """Pack a float in big-endian format"""
    return struct.pack('>f', value)

def unpack_float(data: bytes, offset: int = 0) -> float:
    """Unpack a float from big-endian format"""
    return struct.unpack('>f', data[offset:offset+4])[0]
