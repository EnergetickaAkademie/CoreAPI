import struct
import sys
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class _TestUserConfig:
    def get_board_display_name(self, board_id):
        return None


sys.modules.setdefault(
    "user_config",
    types.SimpleNamespace(get_user_config=lambda: _TestUserConfig()),
)

from binary_protocol import BinaryProtocolError, BoardBinaryProtocol
from state import BoardState, GameState
from state_store import BoardStateStore


class ProtocolCorrectnessTests(unittest.TestCase):
    def test_connection_status_uses_freshest_transport(self):
        board = BoardState("board1")
        board.last_updated = time.time() - 30
        board.mqtt_last_seen = time.time()
        board.mqtt_online = True
        self.assertTrue(board.is_connected())

        board.mqtt_online = False
        self.assertFalse(board.is_connected())

        board.update_last_activity()
        self.assertTrue(board.is_connected())

    def test_registration_request_round_trip(self):
        payload = BoardBinaryProtocol.pack_registration_request(7, "main", "esp32")
        self.assertEqual(
            BoardBinaryProtocol.unpack_registration_request(payload),
            (7, "main", "esp32"),
        )

    def test_signed_power_payload_supports_negative_generation(self):
        payload = struct.pack(">ii", -125, 900)
        self.assertEqual(struct.unpack(">ii", payload), (-125, 900))

    def test_sync_v2_request_round_trip(self):
        payload = BoardBinaryProtocol.pack_sync_v2_request(
            sequence=42,
            production=-125,
            consumption=900,
            production_by_source=[0, 10, 20, 30, 40, 50, 60, 70, -80],
        )
        self.assertEqual(len(payload), 52)
        self.assertEqual(
            BoardBinaryProtocol.unpack_sync_v2_request(payload),
            {
                "sequence": 42,
                "production": -125,
                "consumption": 900,
                "production_by_source": [0, 10, 20, 30, 40, 50, 60, 70, -80],
            },
        )

    def test_sync_v2_response_round_trip(self):
        payload = BoardBinaryProtocol.pack_sync_v2_response(
            sequence=42,
            config_revision=7,
            game_active=True,
            coefficients_milli=list(range(9)),
            min_power_milli=list(range(-9, 0)),
            max_power_milli=list(range(9, 18)),
            consumption_milli=list(range(18)),
            building_counts=list(range(18)),
        )
        self.assertEqual(len(payload), 210)
        decoded = BoardBinaryProtocol.unpack_sync_v2_response(payload)
        self.assertEqual(decoded["sequence"], 42)
        self.assertEqual(decoded["config_revision"], 7)
        self.assertTrue(decoded["game_active"])
        self.assertEqual(decoded["min_power_milli"], list(range(-9, 0)))
        self.assertEqual(decoded["building_counts"], list(range(18)))

    def test_sync_v2_firmware_mode_flag_preserves_fixed_size(self):
        payload = BoardBinaryProtocol.pack_sync_v2_response(
            sequence=1,
            config_revision=2,
            game_active=False,
            firmware_mode=True,
            coefficients_milli=[0] * 9,
            min_power_milli=[0] * 9,
            max_power_milli=[0] * 9,
            consumption_milli=[0] * 18,
            building_counts=[0] * 18,
        )
        self.assertEqual(len(payload), 210)
        self.assertTrue(BoardBinaryProtocol.unpack_sync_v2_response(payload)["firmware_mode"])

    def test_sync_v2_rejects_wrong_magic_and_length(self):
        with self.assertRaises(BinaryProtocolError):
            BoardBinaryProtocol.unpack_sync_v2_request(b"short")

        payload = bytearray(BoardBinaryProtocol.pack_sync_v2_request(1, 2, 3, [0] * 9))
        payload[0:2] = b"XX"
        with self.assertRaises(BinaryProtocolError):
            BoardBinaryProtocol.unpack_sync_v2_request(bytes(payload))

    def test_coefficients_reject_missing_sections(self):
        with self.assertRaises(BinaryProtocolError):
            BoardBinaryProtocol.unpack_coefficients_response(b"\x00")

        with self.assertRaises(BinaryProtocolError):
            BoardBinaryProtocol.unpack_coefficients_response(b"\x00\x00")

    def test_missing_board_returns_none(self):
        self.assertIsNone(GameState(None).get_board("missing"))

    def test_nfc_registration_is_idempotent_and_detects_conflicts(self):
        board = BoardState("board1")

        self.assertEqual(board.register_building("04-aabb", 7), "added")
        self.assertEqual(board.register_building("04-aabb", 7), "duplicate")
        self.assertEqual(board.get_counts()[7], 1)
        self.assertEqual(board.register_building("04-aabb", 8), "conflict")
        self.assertEqual(board.get_counts()[7], 1)
        self.assertEqual(board.get_counts()[8], 0)

    def test_building_reset_clears_counts_and_uid_registrations(self):
        board = BoardState("board1")
        self.assertEqual(board.register_building("04-aabb", 7), "added")
        self.assertEqual(board.register_building("04-ccdd", 8), "added")

        board.clear_registered_buildings()

        self.assertEqual(board.get_counts(), [0] * 18)
        self.assertEqual(board.get_connected_buildings(), [])
        self.assertEqual(board.register_building("04-aabb", 7), "added")

    def test_removing_building_decrements_count_and_allows_readd(self):
        board = BoardState("board1")
        self.assertEqual(board.register_building("04-aabb", 7), "added")
        self.assertTrue(board.remove_connected_building("04-aabb"))
        self.assertEqual(board.get_counts()[7], 0)
        self.assertEqual(board.get_connected_buildings(), [])
        self.assertFalse(board.remove_connected_building("04-aabb"))
        self.assertEqual(board.register_building("04-aabb", 7), "added")
        self.assertEqual(board.get_counts()[7], 1)

    def test_lowering_authoritative_counts_prunes_stale_uids(self):
        board = BoardState("board1")
        self.assertEqual(board.register_building("04-aabb", 7), "added")
        self.assertEqual(board.register_building("04-ccdd", 7), "added")

        counts = board.get_counts()
        counts[7] = 1
        board.set_counts(counts)

        self.assertEqual(board.get_counts()[7], 1)
        self.assertEqual(len(board.get_connected_buildings()), 1)
        removed_uid = ({"04-aabb", "04-ccdd"} - {
            board.get_connected_buildings()[0]["uid"]
        }).pop()
        self.assertEqual(board.register_building(removed_uid, 7), "added")
        self.assertEqual(board.get_counts()[7], 2)

    def test_board_state_survives_store_reopen(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "board_state.db"
            board = BoardState("board1")
            self.assertEqual(board.register_building("04-aabb", 7), "added")

            BoardStateStore(str(db_path)).save(
                "group1", board.id, board.get_persistent_state()
            )
            saved = BoardStateStore(str(db_path)).load_group("group1")

            restored = BoardState("board1")
            restored.restore_persistent_state(saved[0])
            self.assertEqual(restored.get_counts()[7], 1)
            self.assertEqual(
                restored.get_connected_buildings(),
                [{"uid": "04-aabb", "building_type": 7}],
            )


if __name__ == "__main__":
    unittest.main()
