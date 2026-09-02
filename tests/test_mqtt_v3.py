import tempfile
import unittest
from pathlib import Path

from mqtt_protocol import (MqttProtocolError, STATE, TELEMETRY, decode_json,
                           pack_state, pack_telemetry, unpack_state,
                           unpack_telemetry)
from sse_hub import EventHub
from state_store import BoardStateStore


class MqttV3ProtocolTests(unittest.TestCase):
    def test_exact_binary_sizes_and_signed_big_endian_values(self):
        telemetry = pack_telemetry(7, 9, 11, -12, 13, list(range(-1, 8)))
        self.assertEqual(len(telemetry), 60)
        self.assertEqual(unpack_telemetry(telemetry)["production"], -12)
        self.assertEqual(unpack_telemetry(telemetry)["production_by_source"][0], -1)

        state = pack_state(0x0102030405060708, 4, True, False,
                           list(range(9)), list(range(-9, 0)), list(range(9, 18)),
                           list(range(18)), list(range(18)))
        self.assertEqual(len(state), 214)
        decoded = unpack_state(state)
        self.assertEqual(decoded["epoch"], 0x0102030405060708)
        self.assertEqual(decoded["min_power_milli"], list(range(-9, 0)))

    def test_malformed_and_out_of_range_values_are_rejected(self):
        with self.assertRaises(MqttProtocolError):
            unpack_telemetry(b"\0" * (TELEMETRY.size - 1))
        with self.assertRaises(MqttProtocolError):
            unpack_state(b"\0" * STATE.size)
        with self.assertRaises(MqttProtocolError):
            pack_telemetry(-1, 0, 0, 0, 0, [0] * 9)
        with self.assertRaises(MqttProtocolError):
            decode_json(b'{"v":2}')

    def test_event_results_survive_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.db")
            store = BoardStateStore(path)
            ack = {"v": 3, "event_id": 8, "status": "applied"}
            store.save_mqtt_event_ack("group1", "board1", 2, 8, ack)
            self.assertEqual(BoardStateStore(path).get_mqtt_event_ack(
                "group1", "board1", 2, 8), ack)


class EventHubTests(unittest.TestCase):
    def test_replay_and_resync_cursor(self):
        hub = EventHub(history_size=2)
        hub.publish("g", "board_delta", {"board_id": "b1"})
        hub.publish("g", "board_delta", {"board_id": "b1"})
        hub.publish("g", "board_delta", {"board_id": "b1"})
        subscriber = hub.subscribe("g", 0)
        self.assertEqual(subscriber.get_nowait()["event"], "resync")
        hub.unsubscribe("g", subscriber)


if __name__ == "__main__":
    unittest.main()
