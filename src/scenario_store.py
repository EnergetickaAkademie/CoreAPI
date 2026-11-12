"""Persistence for lecturer-created scenarios and their uploaded slide images."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_PREFIX = "uploads/"
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_EXTENSIONS_FOR_LIBRARY = ALLOWED_IMAGE_EXTENSIONS | {".svg"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# File signatures, so a renamed non-image is rejected.
_MAGIC = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],
}


def safe_owner(owner: str) -> str:
    """Filesystem-safe directory name for a username."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", owner or "unknown").strip(".") or "unknown"


def presentations_dir() -> str:
    """Directory with the built-in slides.

    In Docker the presentations are copied next to main.py; when running from
    the repository they live one level up.
    """
    configured = os.environ.get("PRESENTATIONS_DIR")
    if configured:
        return os.path.realpath(configured)
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "presentations")
    if os.path.isdir(local):
        return os.path.realpath(local)
    return os.path.realpath(os.path.join(here, "..", "presentations"))


def uploads_dir() -> str:
    return os.path.realpath(os.environ.get("SCENARIO_UPLOADS_DIR", "data/scenario_uploads"))


def _inside(base: str, path: str) -> bool:
    return path == base or path.startswith(base + os.sep)


def resolve_slide_path(relative: str) -> Optional[str]:
    """Absolute path of a slide referenced by a scenario, or None if invalid."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        return None
    if relative.startswith(UPLOAD_PREFIX):
        base = uploads_dir()
        candidate = os.path.realpath(os.path.join(base, relative[len(UPLOAD_PREFIX):]))
    else:
        base = presentations_dir()
        candidate = os.path.realpath(os.path.join(base, relative))
    return candidate if _inside(base, candidate) else None


def image_exists_for(owner: str):
    """Image check used by validation: library files or the owner's uploads."""
    own_prefix = f"{UPLOAD_PREFIX}{safe_owner(owner)}/"

    def check(relative: str) -> bool:
        if relative.startswith(UPLOAD_PREFIX) and not relative.startswith(own_prefix):
            return False
        path = resolve_slide_path(relative)
        return bool(path) and os.path.isfile(path)

    return check


def list_presentation_files() -> List[str]:
    base = presentations_dir()
    files: List[str] = []
    for root, _dirs, names in os.walk(base):
        for name in names:
            if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS_FOR_LIBRARY:
                files.append(os.path.relpath(os.path.join(root, name), base).replace(os.sep, "/"))
    return sorted(files)


def list_uploads(owner: str) -> List[str]:
    directory = os.path.join(uploads_dir(), safe_owner(owner))
    if not os.path.isdir(directory):
        return []
    return sorted(
        f"{UPLOAD_PREFIX}{safe_owner(owner)}/{name}"
        for name in os.listdir(directory)
        if os.path.splitext(name)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def save_upload(owner: str, filename: str, data: bytes) -> str:
    """Store an uploaded slide image; returns its scenario path. Raises ValueError."""
    extension = os.path.splitext(filename or "")[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Podporované formáty jsou PNG, JPG, GIF a WEBP.")
    if not data:
        raise ValueError("Soubor je prázdný.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Soubor je příliš velký (max. 10 MB).")
    if not any(data.startswith(magic) for magic in _MAGIC[extension]):
        raise ValueError("Soubor není platný obrázek.")
    if extension == ".webp" and data[8:12] != b"WEBP":
        raise ValueError("Soubor není platný obrázek.")

    directory = os.path.join(uploads_dir(), safe_owner(owner))
    os.makedirs(directory, exist_ok=True)
    name = f"{uuid.uuid4().hex}{'.jpg' if extension == '.jpeg' else extension}"
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(data)
    return f"{UPLOAD_PREFIX}{safe_owner(owner)}/{name}"


class ScenarioStore:
    """SQLite table of custom scenarios, each owned by one lecturer."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_scenarios (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_scenarios_owner ON custom_scenarios(owner)"
            )

    @staticmethod
    def _summary(row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "owner": row["owner"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_for_owner(self, owner: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, owner, created_at, updated_at FROM custom_scenarios "
                "WHERE owner = ? ORDER BY name COLLATE NOCASE, created_at",
                (owner,),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, scenario_id: str, owner: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the scenario (with ``document``); restricted to ``owner`` when given."""
        query = "SELECT * FROM custom_scenarios WHERE id = ?"
        params: tuple = (scenario_id,)
        if owner is not None:
            query += " AND owner = ?"
            params += (owner,)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        result = self._summary(row)
        result["document"] = json.loads(row["document_json"])
        return result

    def create(self, owner: str, group_id: str, document: Dict[str, Any]) -> str:
        scenario_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO custom_scenarios (id, owner, group_id, name, document_json) VALUES (?, ?, ?, ?, ?)",
                (scenario_id, owner, group_id, document["name"], json.dumps(document, ensure_ascii=False)),
            )
        return scenario_id

    def update(self, scenario_id: str, owner: str, document: Dict[str, Any]) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE custom_scenarios SET name = ?, document_json = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND owner = ?",
                (document["name"], json.dumps(document, ensure_ascii=False), scenario_id, owner),
            )
        return cursor.rowcount > 0

    def delete(self, scenario_id: str, owner: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM custom_scenarios WHERE id = ? AND owner = ?", (scenario_id, owner)
            )
        return cursor.rowcount > 0


_store: Optional[ScenarioStore] = None


def get_scenario_store() -> ScenarioStore:
    global _store
    if _store is None:
        _store = ScenarioStore(os.environ.get("SCENARIO_DB_PATH", "data/scenarios.db"))
    return _store
