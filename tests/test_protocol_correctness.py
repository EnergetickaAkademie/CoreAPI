import struct
import sys
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
    def test_registration_request_round_trip(self):
        payload = BoardBinaryProtocol.pack_registration_request(7, "main", "esp32")
        self.assertEqual(
            BoardBinaryProtocol.unpack_registration_request(payload),
            (7, "main", "esp32"),
        )

    def test_signed_power_payload_supports_negative_generation(self):
        payload = struct.pack(">ii", -125, 900)
        self.assertEqual(struct.unpack(">ii", payload), (-125, 900))

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
