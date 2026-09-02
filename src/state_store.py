"""Durable storage for board registration and NFC building state."""

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List


class BoardStateStore:
    """Persist the small subset of board state that must survive API restarts."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS board_state (
                    group_id TEXT NOT NULL,
                    board_id TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    buildings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, board_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mqtt_event_results (
                    group_id TEXT NOT NULL,
                    board_id TEXT NOT NULL,
                    boot_id INTEGER NOT NULL,
                    event_id INTEGER NOT NULL,
                    ack_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, board_id, boot_id, event_id)
                )
                """
            )

    def save(self, group_id: str, board_id: str, state: Dict[str, Any]):
        counts_json = json.dumps(state["authoritative_counts"], separators=(",", ":"))
        buildings_json = json.dumps(state["connected_buildings"], separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO board_state (group_id, board_id, counts_json, buildings_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id, board_id) DO UPDATE SET
                    counts_json = excluded.counts_json,
                    buildings_json = excluded.buildings_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (group_id, board_id, counts_json, buildings_json),
            )

    def load_group(self, group_id: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT board_id, counts_json, buildings_json
                FROM board_state
                WHERE group_id = ?
                ORDER BY board_id
                """,
                (group_id,),
            ).fetchall()

        restored = []
        for board_id, counts_json, buildings_json in rows:
            try:
                restored.append({
                    "board_id": board_id,
                    "authoritative_counts": json.loads(counts_json),
                    "connected_buildings": json.loads(buildings_json),
                })
            except (TypeError, json.JSONDecodeError):
                # Ignore a corrupt row; a subsequent registration can replace it.
                continue
        return restored

    def get_mqtt_event_ack(self, group_id: str, board_id: str,
                           boot_id: int, event_id: int) -> Dict[str, Any] | None:
        """Return the original acknowledgement for an already applied event."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ack_json FROM mqtt_event_results
                WHERE group_id = ? AND board_id = ? AND boot_id = ? AND event_id = ?
                """, (group_id, board_id, boot_id, event_id)
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def save_mqtt_event_ack(self, group_id: str, board_id: str,
                            boot_id: int, event_id: int,
                            ack: Dict[str, Any]) -> None:
        """Persist an application-level MQTT event result idempotently."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO mqtt_event_results
                    (group_id, board_id, boot_id, event_id, ack_json)
                VALUES (?, ?, ?, ?, ?)
                """, (group_id, board_id, boot_id, event_id,
                       json.dumps(ack, separators=(",", ":")))
            )
