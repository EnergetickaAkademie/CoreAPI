"""In-process, bounded SSE fan-out for dashboard updates."""

from __future__ import annotations

import queue
import threading
from collections import defaultdict, deque
from typing import Any


class EventHub:
    def __init__(self, history_size: int = 512):
        self.history_size = history_size
        self._lock = threading.Lock()
        self._sequence = 0
        self._history = defaultdict(lambda: deque(maxlen=self.history_size))
        self._subscribers = defaultdict(set)

    def publish(self, group_id: str, event: str, data: dict[str, Any]) -> int:
        with self._lock:
            self._sequence += 1
            item = {"id": self._sequence, "event": event, "data": data}
            self._history[group_id].append(item)
            subscribers = list(self._subscribers[group_id])
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(item)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait({"id": self._sequence, "event": "resync", "data": {}})
                except queue.Full:
                    pass
        return self._sequence

    def cursor(self) -> int:
        with self._lock:
            return self._sequence

    def snapshot(self, group_id: str) -> tuple[int, list[dict[str, Any]]]:
        """Return a consistent cursor and the currently replayable events."""
        with self._lock:
            return self._sequence, list(self._history[group_id])

    def subscribe(self, group_id: str, after: int = 0):
        subscriber: queue.Queue = queue.Queue(maxsize=128)
        with self._lock:
            history = list(self._history[group_id])
            if history and after < history[0]["id"] - 1:
                subscriber.put_nowait({"id": self._sequence, "event": "resync", "data": {}})
            else:
                for item in history:
                    if item["id"] > after:
                        try:
                            subscriber.put_nowait(item)
                        except queue.Full:
                            break
            self._subscribers[group_id].add(subscriber)
        return subscriber

    def unsubscribe(self, group_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers[group_id].discard(subscriber)
