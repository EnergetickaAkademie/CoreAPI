"""Wire formats and validation for the workshop MQTT v3 transport."""

from __future__ import annotations

import json
import re
import struct
from typing import Any

MAGIC = b"EA"
VERSION = 3
SOURCE_COUNT = 9
BUILDING_COUNT = 18
TELEMETRY = struct.Struct(">2sBBIIIii9i")
STATE = struct.Struct(">2sBBQI45i18B")
MAX_JSON_BYTES = 4096
BOARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class MqttProtocolError(ValueError):
    pass


def _check_board_id(board_id: str) -> str:
    if not isinstance(board_id, str) or not BOARD_ID_RE.fullmatch(board_id):
        raise MqttProtocolError("invalid board id")
    return board_id


def pack_telemetry(boot_id: int, sequence: int, uptime_ms: int,
                   production: int, consumption: int,
                   production_by_source: list[int]) -> bytes:
    if len(production_by_source) != SOURCE_COUNT:
        raise MqttProtocolError("telemetry requires exactly 9 source values")
    if any(not isinstance(value, int) or not 0 <= value <= 0xffffffff
           for value in (boot_id, sequence, uptime_ms)):
        raise MqttProtocolError("telemetry unsigned fields are out of range")
    try:
        return TELEMETRY.pack(MAGIC, VERSION, 0, boot_id & 0xffffffff,
                              sequence & 0xffffffff, uptime_ms & 0xffffffff,
                              production, consumption, *production_by_source)
    except struct.error as exc:
        raise MqttProtocolError(str(exc)) from exc


def unpack_telemetry(payload: bytes) -> dict[str, Any]:
    if len(payload) != TELEMETRY.size:
        raise MqttProtocolError(f"invalid telemetry length {len(payload)}")
    magic, version, flags, boot_id, sequence, uptime_ms, production, consumption, *sources = TELEMETRY.unpack(payload)
    if magic != MAGIC or version != VERSION or flags != 0:
        raise MqttProtocolError("unsupported telemetry header")
    return {"boot_id": boot_id, "sequence": sequence, "uptime_ms": uptime_ms,
            "production": production, "consumption": consumption,
            "production_by_source": sources}


def pack_state(epoch: int, revision: int, game_active: bool, firmware_mode: bool,
               coefficients_milli: list[int], min_power_milli: list[int],
               max_power_milli: list[int], consumption_milli: list[int],
               building_counts: list[int]) -> bytes:
    vectors = (coefficients_milli, min_power_milli, max_power_milli)
    if any(len(values) != SOURCE_COUNT for values in vectors):
        raise MqttProtocolError("state requires exactly 9 source values")
    if len(consumption_milli) != BUILDING_COUNT or len(building_counts) != BUILDING_COUNT:
        raise MqttProtocolError("state requires exactly 18 building values")
    if (not isinstance(epoch, int) or not 0 <= epoch <= 0xffffffffffffffff or
            not isinstance(revision, int) or not 0 <= revision <= 0xffffffff):
        raise MqttProtocolError("state epoch or revision is out of range")
    if any(not isinstance(value, int) for values in vectors + (consumption_milli,)
           for value in values):
        raise MqttProtocolError("state values must be integers")
    if any(value < 0 for value in consumption_milli):
        raise MqttProtocolError("state consumption values must be non-negative")
    if any(not isinstance(value, int) or not 0 <= value <= 255 for value in building_counts):
        raise MqttProtocolError("building counts must be bytes")
    flags = (1 if game_active else 0) | (2 if firmware_mode else 0)
    try:
        return STATE.pack(MAGIC, VERSION, flags, epoch,
                          revision, *coefficients_milli,
                          *min_power_milli, *max_power_milli,
                          *consumption_milli, *building_counts)
    except struct.error as exc:
        raise MqttProtocolError(str(exc)) from exc


def unpack_state(payload: bytes) -> dict[str, Any]:
    if len(payload) != STATE.size:
        raise MqttProtocolError(f"invalid state length {len(payload)}")
    magic, version, flags, epoch, revision, *values = STATE.unpack(payload)
    if magic != MAGIC or version != VERSION or flags & ~0x03:
        raise MqttProtocolError("unsupported state header")
    return {
        "epoch": epoch,
        "revision": revision,
        "game_active": bool(flags & 0x01),
        "firmware_mode": bool(flags & 0x02),
        "coefficients_milli": values[0:9],
        "min_power_milli": values[9:18],
        "max_power_milli": values[18:27],
        "consumption_milli": values[27:45],
        "building_counts": values[45:63],
    }


def encode_json(message: dict[str, Any]) -> bytes:
    if not isinstance(message, dict) or message.get("v") != VERSION:
        raise MqttProtocolError("JSON message must contain v=3")
    try:
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode()
    except (TypeError, ValueError) as exc:
        raise MqttProtocolError(str(exc)) from exc
    if len(payload) > MAX_JSON_BYTES:
        raise MqttProtocolError("JSON message exceeds size limit")
    return payload


def decode_json(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, (bytes, bytearray)) or len(payload) > MAX_JSON_BYTES:
        raise MqttProtocolError("JSON message exceeds size limit")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MqttProtocolError("invalid JSON message") from exc
    if not isinstance(message, dict) or message.get("v") != VERSION:
        raise MqttProtocolError("unsupported JSON message version")
    return message


def topic_root(board_id: str) -> str:
    return f"enak/v3/boards/{_check_board_id(board_id)}"
