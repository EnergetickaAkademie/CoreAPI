import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class _TestUserConfig:
    def get_board_display_name(self, board_id):
        return None


sys.modules.setdefault(
    "user_config",
    types.SimpleNamespace(get_user_config=lambda: _TestUserConfig()),
)
try:
    import toml  # noqa: F401
except ModuleNotFoundError:
    sys.modules["toml"] = types.SimpleNamespace()

from firmware_manager import FirmwareManager


class _Response:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class DirectOtaTests(unittest.TestCase):
    def _manager(self):
        manager = FirmwareManager.__new__(FirmwareManager)
        manager.store = Mock()
        manager._ota_password = Mock(return_value="long-enough-password")
        manager._wait_for_pull_board = Mock()
        return manager

    def _job_and_board(self):
        board = {
            "board_id": "w2b5",
            "address": "10.0.1.102",
            "port": 8080,
            "transport": "direct",
            "state": "pending",
            "error": None,
        }
        return {"version": "0.3.0", "boards": [board]}, board

    def test_direct_upload_uses_original_single_post_transport(self):
        manager = self._manager()
        job, board = self._job_and_board()

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "firmware.bin"
            image.write_bytes(b"firmware-image")
            with patch("firmware_manager.requests.post") as post, patch(
                "firmware_manager.requests.get"
            ) as get:
                post.return_value = _Response()
                get.side_effect = [
                    _Response({"board_id": "w2b5"}),
                    _Response({"board_id": "w2b5", "firmware_version": "0.3.0"}),
                ]

                manager._run_direct_board(job, board, image)

        self.assertEqual(board["state"], "succeeded")
        self.assertEqual(post.call_count, 1)
        upload_call = post.call_args
        self.assertEqual(upload_call.args[0], "http://10.0.1.102:8080/ota/firmware")
        self.assertNotIn("X-Firmware-Size", upload_call.kwargs["headers"])
        self.assertEqual(
            get.call_args_list[0],
            call(
                "http://10.0.1.102:8080/ota/status",
                headers={"X-OTA-Password": "long-enough-password"},
                timeout=(2, 3),
            ),
        )

    def test_connection_failure_before_upload_switches_to_pull(self):
        manager = self._manager()
        job, board = self._job_and_board()

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "firmware.bin"
            image.write_bytes(b"firmware-image")
            with patch(
                "firmware_manager.requests.get",
                side_effect=requests.ConnectionError("unreachable"),
            ):
                manager._run_direct_board(job, board, image)

        self.assertEqual(board["transport"], "pull")
        manager._wait_for_pull_board.assert_called_once_with(job, board)

    def test_connection_failure_during_upload_does_not_retry_with_pull(self):
        manager = self._manager()
        job, board = self._job_and_board()

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "firmware.bin"
            image.write_bytes(b"firmware-image")
            with patch("firmware_manager.requests.post") as post, patch(
                "firmware_manager.requests.get",
                return_value=_Response({"board_id": "w2b5"}),
            ):
                post.side_effect = requests.ConnectionError("upload interrupted")
                manager._run_direct_board(job, board, image)

        self.assertEqual(board["transport"], "direct")
        self.assertEqual(board["state"], "failed")
        manager._wait_for_pull_board.assert_not_called()


if __name__ == "__main__":
    unittest.main()
