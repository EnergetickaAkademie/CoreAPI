"""Firmware catalog and sequential mainboard OTA orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import requests


MAX_FIRMWARE_BYTES = 16 * 1024 * 1024
SEMVER_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def semver(value: str):
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {value}")
    pre = match.group(4)
    identifiers = () if not pre else tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in pre.split(".")
    )
    # Stable versions sort after prereleases.
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
            (1, ()) if pre is None else (0, identifiers))


def normalize_version(value: str) -> str:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {value}")
    return ".".join(match.group(i) for i in range(1, 4)) + (
        f"-{match.group(4)}" if match.group(4) else "")


class FirmwareStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS firmware_jobs (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL, version TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                payload_json TEXT NOT NULL)""")

    def save(self, job: dict[str, Any]):
        now = time.time()
        job["updated_at"] = now
        with sqlite3.connect(self.db_path) as db:
            db.execute("""INSERT INTO firmware_jobs
                (id, group_id, version, state, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,
                updated_at=excluded.updated_at, payload_json=excluded.payload_json""",
                (job["id"], job["group_id"], job["version"], job["state"],
                 job["created_at"], now, json.dumps(job)))

    def load(self, job_id: str):
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT payload_json FROM firmware_jobs WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def recover(self):
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute("SELECT payload_json FROM firmware_jobs WHERE state IN ('running','queued')").fetchall()
        jobs = []
        for row in rows:
            job = json.loads(row[0])
            if job["state"] == "running":
                job["state"] = "interrupted"
                for board in job.get("boards", []):
                    if board.get("state") in ("running", "uploading", "rebooting"):
                        board["state"] = "interrupted"
                        board["error"] = "CoreAPI restarted during update"
                self.save(job)
            elif job["state"] == "queued":
                jobs.append(job)
        return jobs


class FirmwareManager:
    def __init__(self, state_dir: str, get_game_active: Callable[[str], bool], get_board: Callable[[str, str], Any]):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = FirmwareStore(str(self.state_dir / "firmware_jobs.db"))
        self.get_game_active = get_game_active
        self.get_board = get_board
        self.shared_ota_password = os.getenv("OTA_PASSWORD", "")
        self.github_repo = os.getenv("FIRMWARE_GITHUB_REPOSITORY", "EnergetickaAkademie/v2-firmware")
        self.manifest_url = os.getenv("FIRMWARE_MANIFEST_URL", "").strip()
        self.cache_seconds = max(30, int(os.getenv("FIRMWARE_CATALOG_CACHE_SECONDS", "300")))
        self.ota_port = int(os.getenv("FIRMWARE_OTA_PORT", "8080"))
        self.catalog_cache = None
        self.catalog_at = 0.0
        self.catalog_stale = False
        self.work = queue.Queue()
        self.worker_lock = threading.Lock()
        self.active_job = None
        self.thread = threading.Thread(target=self._worker, name="firmware-ota", daemon=True)
        self.thread.start()
        recovered_jobs = self.store.recover()
        if recovered_jobs:
            self.active_job = recovered_jobs[0]["id"]
        for job in recovered_jobs:
            self.work.put(job["id"])

    def probe(self, board):
        """Refresh version/readiness from the board's last trusted address."""
        address = getattr(board, "network_address", None)
        if not address or not self.shared_ota_password:
            return
        port = getattr(board, "ota_port", 0) or self.ota_port
        try:
            response = requests.get(f"http://{address}:{port}/ota/status",
                                    headers={"X-OTA-Password": self.shared_ota_password}, timeout=(1, 2))
            if not response.ok:
                board.firmware_error = f"OTA status HTTP {response.status_code}"
                return
            payload = response.json()
            if payload.get("board_id") and payload.get("board_id") != board.id:
                board.firmware_error = "OTA status board identity mismatch"
                board.ota_ready = False
                return
            if payload.get("firmware_version"):
                board.firmware_version = payload["firmware_version"]
            if payload.get("ota_port"):
                board.ota_port = int(payload["ota_port"])
            if "ota_ready" in payload:
                board.ota_ready = bool(payload["ota_ready"])
            if payload.get("config_schema") is not None:
                board.config_schema = int(payload["config_schema"])
            board.firmware_error = None
        except (requests.RequestException, ValueError, TypeError) as exc:
            board.firmware_error = str(exc)

    def _github_releases(self):
        headers = {"Accept": "application/vnd.github+json"}
        if os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
        response = requests.get(f"https://api.github.com/repos/{self.github_repo}/releases",
                                headers=headers, params={"per_page": 100}, timeout=(5, 15))
        response.raise_for_status()
        releases = []
        for release in response.json():
            if release.get("draft"):
                continue
            try:
                version = normalize_version(release.get("tag_name", ""))
            except ValueError:
                continue
            assets = {asset.get("name"): asset for asset in release.get("assets", [])}
            image = assets.get("mb_firmware.bin")
            metadata = assets.get("mb_firmware.json")
            checksum = None
            size = image.get("size") if image else None
            if metadata:
                meta_response = requests.get(metadata["browser_download_url"], timeout=(5, 10))
                meta_response.raise_for_status()
                meta = meta_response.json()
                checksum = meta.get("sha256")
                size = meta.get("size", size)
            if not checksum:
                checksum_asset = assets.get("mb_firmware.bin.sha256")
                if checksum_asset:
                    checksum_response = requests.get(checksum_asset["browser_download_url"], timeout=(5, 10))
                    checksum_response.raise_for_status()
                    checksum = checksum_response.text.strip().split()[0]
            if not image or not checksum:
                continue
            releases.append({"version": version, "channel": "prerelease" if release.get("prerelease") else "stable",
                             "published_at": release.get("published_at"), "notes_url": release.get("html_url"),
                             "asset_url": image["browser_download_url"], "sha256": checksum.lower(),
                             "size": size, "config_schema": 1, "source": "github"})
        return releases

    def _manifest_releases(self):
        if not self.manifest_url:
            return []
        if not self.manifest_url.startswith("https://"):
            raise ValueError("FIRMWARE_MANIFEST_URL must use HTTPS")
        response = requests.get(self.manifest_url, timeout=(5, 15))
        response.raise_for_status()
        result = []
        for item in response.json().get("releases", []):
            version = normalize_version(item["version"])
            asset = item.get("asset") or item
            if not asset.get("url", "").startswith("https://"):
                raise ValueError("Firmware assets must use HTTPS")
            checksum = str(asset.get("sha256", "")).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError(f"Missing or invalid SHA-256 for {version}")
            result.append({"version": version, "channel": item.get("channel", "stable"),
                           "published_at": item.get("published_at"), "notes_url": item.get("notes_url"),
                           "asset_url": asset["url"], "sha256": checksum, "size": asset.get("size"),
                           "config_schema": int(item.get("config_schema", 1)), "source": "domain"})
        return result

    def releases(self, refresh=False):
        if not refresh and self.catalog_cache is not None and time.time() - self.catalog_at < self.cache_seconds:
            return {"releases": self.catalog_cache, "stale": self.catalog_stale}
        errors = []
        candidates = []
        for fetch in (self._github_releases, self._manifest_releases):
            try:
                candidates.extend(fetch())
            except Exception as exc:
                errors.append(str(exc))
        merged = {}
        conflicts = set()
        for release in candidates:
            key = release["version"]
            if key in merged and merged[key]["sha256"] != release["sha256"]:
                conflicts.add(key)
                continue
            if key not in merged or release["source"] == "github":
                merged[key] = release
            elif release["source"] != merged[key]["source"]:
                merged[key].setdefault("mirrors", []).append(release["asset_url"])
        output = []
        for version, release in merged.items():
            release["conflict"] = version in conflicts
            output.append(release)
        output.sort(key=lambda item: semver(item["version"]), reverse=True)
        if output:
            self.catalog_cache, self.catalog_at, self.catalog_stale = output, time.time(), bool(errors)
        elif self.catalog_cache is not None:
            self.catalog_stale = True
        if not output and self.catalog_cache is None:
            raise RuntimeError("No firmware catalog is available: " + "; ".join(errors))
        return {"releases": self.catalog_cache or output, "stale": self.catalog_stale, "errors": errors}

    def _download(self, release):
        if not re.fullmatch(r"[0-9a-f]{64}", str(release.get("sha256", "")).lower()):
            raise ValueError("Release metadata contains an invalid SHA-256")
        target = self.state_dir / "cache" / f"{release['sha256']}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == release["sha256"]:
            return target
        response = requests.get(release["asset_url"], stream=True, timeout=(5, 30))
        response.raise_for_status()
        digest = hashlib.sha256()
        total = 0
        tmp = target.with_suffix(".tmp")
        with tmp.open("wb") as output:
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_FIRMWARE_BYTES:
                    raise ValueError("Firmware image exceeds 16 MiB")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != release["sha256"]:
            tmp.unlink(missing_ok=True)
            raise ValueError("Firmware SHA-256 does not match release metadata")
        if tmp.stat().st_size < 4 or tmp.read_bytes()[:1] != b"\xe9":
            tmp.unlink(missing_ok=True)
            raise ValueError("Downloaded file is not an ESP32 image")
        tmp.replace(target)
        return target

    def create_job(self, group_id, version, board_ids, confirm_non_upgrade=False):
        if self.get_game_active(group_id):
            raise ValueError("Cannot update firmware while a game is active")
        release = next((r for r in self.releases()["releases"] if r["version"] == normalize_version(version)), None)
        if not release or release.get("conflict"):
            raise ValueError("Requested firmware release is unavailable or has a checksum conflict")
        targets = []
        for board_id in board_ids:
            board = self.get_board(group_id, board_id)
            if not board:
                raise ValueError(f"Unknown board: {board_id}")
            current = getattr(board, "firmware_version", None)
            if current:
                try:
                    is_non_upgrade = semver(current) >= semver(release["version"])
                except ValueError:
                    is_non_upgrade = False
                if is_non_upgrade and not confirm_non_upgrade:
                    raise ValueError(f"{board_id} requires confirmation for downgrade or reinstall")
            if not getattr(board, "network_address", None):
                raise ValueError(f"{board_id} has no trusted network address")
            if not getattr(board, "ota_ready", False):
                raise ValueError(f"{board_id} requires bootstrap provisioning")
            targets.append({"board_id": board_id, "address": board.network_address,
                            "port": getattr(board, "ota_port", 0) or self.ota_port,
                            "current_version": current, "state": "queued"})
        if not targets:
            raise ValueError("At least one board must be selected")
        with self.worker_lock:
            if self.active_job:
                raise ValueError("Another firmware rollout is already active")
            job = {"id": uuid.uuid4().hex, "group_id": group_id, "version": release["version"],
                   "release": release, "boards": targets, "state": "queued", "created_at": time.time()}
            self.store.save(job)
            self.active_job = job["id"]
            self.work.put(job["id"])
        return job

    def get_job(self, job_id):
        return self.store.load(job_id)

    def _worker(self):
        while True:
            job_id = self.work.get()
            job = self.store.load(job_id)
            if not job:
                continue
            try:
                self._run_job(job)
            finally:
                with self.worker_lock:
                    if self.active_job == job_id:
                        self.active_job = None
                self.work.task_done()

    def _run_job(self, job):
        job["state"] = "running"
        self.store.save(job)
        try:
            image = self._download(job["release"])
        except Exception as exc:
            job["state"] = "failed"
            job["error"] = str(exc)
            for board in job["boards"]:
                board["state"], board["error"] = "failed", str(exc)
            self.store.save(job)
            return
        for board in job["boards"]:
            if self.get_game_active(job["group_id"]):
                board["state"], board["error"] = "blocked", "Game became active"
                self.store.save(job)
                continue
            board["state"] = "uploading"
            self.store.save(job)
            try:
                if not self.shared_ota_password:
                    raise ValueError("OTA_PASSWORD is not configured in CoreAPI")
                url = f"http://{board['address']}:{board['port']}/ota/firmware"
                with image.open("rb") as stream:
                    response = requests.post(url, headers={"X-OTA-Password": self.shared_ota_password},
                                             files={"firmware": ("mb_firmware.bin", stream, "application/octet-stream")},
                                             timeout=(5, 180))
                if not response.ok:
                    raise RuntimeError(f"Board returned HTTP {response.status_code}: {response.text[:200]}")
                board["state"] = "rebooting"
                self.store.save(job)
                deadline = time.time() + 90
                verified = False
                while time.time() < deadline:
                    try:
                        status = requests.get(f"http://{board['address']}:{board['port']}/ota/status",
                                              headers={"X-OTA-Password": self.shared_ota_password}, timeout=(2, 3))
                        if status.ok:
                            payload = status.json()
                            if payload.get("board_id") == board["board_id"] and payload.get("firmware_version") == job["version"]:
                                verified = True
                                break
                    except (requests.RequestException, ValueError):
                        pass
                    time.sleep(2)
                if not verified:
                    raise TimeoutError("Board did not report the requested firmware after reboot")
                board["state"] = "succeeded"
            except Exception as exc:
                board["state"], board["error"] = "failed", str(exc)
            self.store.save(job)
        states = [b["state"] for b in job["boards"]]
        job["state"] = "succeeded" if all(s == "succeeded" for s in states) else (
            "partial" if any(s == "succeeded" for s in states) else "failed")
        self.store.save(job)
