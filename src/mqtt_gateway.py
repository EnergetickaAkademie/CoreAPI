"""Small, single-process MQTT gateway used by CoreAPI v3.

The gateway deliberately keeps broker callbacks short and hands board
messages to a bounded worker queue.  MQTT telemetry is replaceable state, so
it is coalesced when the worker is busy; events and acknowledgements use the
normal QoS 1 flow and are never silently retried by this layer.
"""

from __future__ import annotations

import os
import queue
import secrets
import threading
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:  # Keep protocol/unit-test imports usable without broker deps.
    mqtt = None

from mqtt_protocol import BOARD_ID_RE, MqttProtocolError, decode_json, topic_root


class MqttGateway:
    def __init__(self, handlers: dict[str, Callable[..., None]]):
        self.enabled = (mqtt is not None and
                        os.getenv("MQTT_ENABLED", "false").lower() in
                        {"1", "true", "yes", "on"})
        self.host = os.getenv("MQTT_HOST", "mosquitto")
        self.port = int(os.getenv("MQTT_PORT", "1883"))
        self.username = os.getenv("MQTT_USERNAME", "coreapi")
        self.password = os.getenv("MQTT_PASSWORD", "")
        self.client_id = os.getenv("MQTT_CLIENT_ID", "coreapi-v3")
        self.keepalive = int(os.getenv("MQTT_KEEPALIVE", "10"))
        self.public_uri = os.getenv("MQTT_PUBLIC_URI", "").strip()
        self.handlers = handlers
        self.epoch = secrets.randbits(64)
        self._connected = threading.Event()
        self._stopping = threading.Event()
        self._publish_lock = threading.Lock()
        self._work: queue.Queue[tuple[str, str, bytes]] = queue.Queue(maxsize=256)
        self._telemetry: dict[str, bytes] = {}
        self._telemetry_lock = threading.Lock()
        self._worker = threading.Thread(target=self._worker_loop, name="mqtt-v3-worker", daemon=True)
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="mqtt-v3-heartbeat", daemon=True)
        self.client = None
        if mqtt is not None:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.client_id,
                clean_session=False,
                protocol=mqtt.MQTTv311,
                transport=os.getenv("MQTT_TRANSPORT", "tcp"),
            )
            if self.username:
                self.client.username_pw_set(self.username, self.password)
            self.client.will_set(
                "enak/v3/server/availability",
                self._availability_payload(False), qos=1, retain=True,
            )
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

    @property
    def healthy(self) -> bool:
        return self.enabled and self._connected.is_set()

    def _availability_payload(self, online: bool) -> bytes:
        from mqtt_protocol import encode_json
        return encode_json({"v": 3, "online": online, "epoch": f"{self.epoch:016x}"})

    def start(self) -> None:
        if not self.enabled:
            return
        self._worker.start()
        self._heartbeat.start()
        try:
            self.client.connect_async(self.host, self.port, self.keepalive)
            self.client.loop_start()
        except Exception:
            self._connected.clear()

    def stop(self) -> None:
        self._stopping.set()
        if not self.enabled:
            return
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != mqtt.ReasonCode(0):
            self._connected.clear()
            return
        subscriptions = [
            ("enak/v3/boards/+/telemetry", 0),
            ("enak/v3/boards/+/events", 1),
            ("enak/v3/boards/+/state-ack", 1),
            ("enak/v3/boards/+/command-ack", 1),
            ("enak/v3/boards/+/availability", 1),
        ]
        client.subscribe(subscriptions)
        self._connected.set()
        self.publish_json("enak/v3/server/availability", {
            "v": 3, "online": True, "epoch": f"{self.epoch:016x}"
        }, qos=1, retain=True)
        callback = self.handlers.get("connected")
        if callback:
            callback()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self._connected.clear()
        callback = self.handlers.get("disconnected")
        if callback:
            callback()

    def _on_message(self, client, userdata, message):
        if len(message.payload) > 4096:
            return
        parts = message.topic.split("/")
        if len(parts) != 5 or parts[0:3] != ["enak", "v3", "boards"]:
            return
        board_id, kind = parts[3], parts[4]
        if not BOARD_ID_RE.fullmatch(board_id):
            return
        if kind == "telemetry":
            with self._telemetry_lock:
                self._telemetry[board_id] = bytes(message.payload)
            return
        try:
            self._work.put_nowait((board_id, kind, bytes(message.payload)))
        except queue.Full:
            callback = self.handlers.get("overload")
            if callback:
                callback(board_id, kind)

    def _worker_loop(self):
        while not self._stopping.is_set():
            try:
                board_id, kind, payload = self._work.get(timeout=0.25)
            except queue.Empty:
                board_id = kind = payload = None
            if board_id is not None:
                handler = self.handlers.get(kind)
                if handler:
                    try:
                        handler(board_id, payload)
                    except Exception:
                        error_handler = self.handlers.get("error")
                        if error_handler:
                            error_handler(board_id, kind)
                self._work.task_done()
            with self._telemetry_lock:
                telemetry = list(self._telemetry.items())
                self._telemetry.clear()
            handler = self.handlers.get("telemetry")
            if handler:
                for board_id, payload in telemetry:
                    try:
                        handler(board_id, payload)
                    except Exception:
                        error_handler = self.handlers.get("error")
                        if error_handler:
                            error_handler(board_id, "telemetry")

    def _heartbeat_loop(self):
        sequence = 0
        while not self._stopping.wait(1.0):
            if self.healthy:
                sequence = (sequence + 1) & 0xffffffff
                self.publish_json("enak/v3/server/heartbeat", {
                    "v": 3, "epoch": f"{self.epoch:016x}", "sequence": sequence
                }, qos=0, retain=False)

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> bool:
        if not self.healthy:
            return False
        if self.client is None or mqtt is None:
            return False
        with self._publish_lock:
            info = self.client.publish(topic, payload, qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def publish_json(self, topic: str, message: dict[str, Any], qos: int = 1, retain: bool = False) -> bool:
        from mqtt_protocol import encode_json
        try:
            return self.publish(topic, encode_json(message), qos=qos, retain=retain)
        except MqttProtocolError:
            return False

    def publish_state(self, board_id: str, payload: bytes) -> bool:
        try:
            root = topic_root(board_id)
        except MqttProtocolError:
            return False
        return self.publish(f"{root}/state", payload, qos=1, retain=True)

    def publish_event_ack(self, board_id: str, message: dict[str, Any]) -> bool:
        return self.publish_json(f"{topic_root(board_id)}/event-ack", message, qos=1)

    def publish_command(self, board_id: str, message: dict[str, Any]) -> bool:
        return self.publish_json(f"{topic_root(board_id)}/commands", message, qos=1)
