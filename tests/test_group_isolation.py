"""Two workshops (groups) on one CoreAPI must only see their own boards.

main.py has import-time side effects (auth DB, user config, MQTT gateway) and
other test modules stub ``user_config`` in sys.modules, so the scenario runs
in a fresh interpreter with its own working directory.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

FIRMWARE_TOML = """
[firmware]
github_repository = "example/firmware"
manifest_url = ""
github_token = ""
catalog_cache_seconds = 300
ota_port = 8080
direct_ota_cidrs = []
"""

USERS_TOML = """
[lecturers]
lecturer1 = { password = "pw1", name = "Lecturer 1", group = "group1" }
hlinsko1 = { password = "pw2", name = "Hlinsko 1", group = "hlinsko" }

[boards]
board1 = { password = "b", ota_password = "o", name = "board1", group = "group1", display_name = "Tym 1", id = 1 }
board2 = { password = "b", ota_password = "o", name = "board2", group = "group1", display_name = "Tym 2", id = 2 }
h1b1 = { password = "b", ota_password = "o", name = "h1b1", group = "hlinsko", display_name = "#1", id = 1 }
h1b2 = { password = "b", ota_password = "o", name = "h1b2", group = "hlinsko", display_name = "#2", id = 2 }
h1b3 = { password = "b", ota_password = "o", name = "h1b3", group = "hlinsko", display_name = "#3", id = 3 }

[groups]
group1 = { name = "Primary", max_boards = 10 }
hlinsko = { name = "Hlinsko", max_boards = 5 }
"""

SCRIPT = textwrap.dedent("""
    import main

    client = main.app.test_client()

    def login(username, password):
        response = client.post('/login', json={'username': username, 'password': password})
        assert response.status_code == 200, (username, response.get_json())
        return {'Authorization': 'Bearer ' + response.get_json()['token']}

    headers = {'group1': login('lecturer1', 'pw1'), 'hlinsko': login('hlinsko1', 'pw2')}
    expected = {'group1': {'board1', 'board2'}, 'hlinsko': {'h1b1', 'h1b2', 'h1b3'}}

    for group, h in headers.items():
        poll = client.get('/pollforusers', headers=h).get_json()
        assert {b['board_id'] for b in poll['boards']} == expected[group], (group, poll['boards'])
        assert set(poll['board_names']) <= expected[group] | {'1', '2'}, poll['board_names']

        firmware = client.get('/lecturer/firmware/boards', headers=h).get_json()
        assert {b['board_id'] for b in firmware['boards']} == expected[group], firmware

        users = client.get('/config/users', headers=h).get_json()
        assert {u['username'] for u in users['boards']} == expected[group], users

    scenario_id = client.get('/scenarios', headers=headers['hlinsko']).get_json()['scenarios'][0]
    started = client.post('/start_game', json={'scenario_id': scenario_id}, headers=headers['hlinsko'])
    assert started.status_code == 200, started.get_json()
    advanced = client.post('/next_round', headers=headers['hlinsko'])
    assert advanced.status_code == 200, advanced.get_json()
    assert main.group_manager.get_game_state('hlinsko').get_script() is not None
    assert main.group_manager.get_game_state('group1').get_script() is None
    assert not main.group_manager.is_game_active('group1')
    print('OK')
""")


class GroupIsolationTests(unittest.TestCase):
    def run_scenario(self, directory, script):
        env = dict(os.environ, PYTHONPATH=str(SRC), MQTT_ENABLED="false",
                   BOARD_STATE_DB_PATH=str(Path(directory) / "data" / "state.db"),
                   FIRMWARE_STATE_DIR=str(Path(directory) / "data" / "firmware"))
        return subprocess.run([sys.executable, "-c", script], cwd=directory,
                              env=env, capture_output=True, text=True, timeout=120)

    def test_lecturers_only_see_their_own_groups_boards(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config").mkdir()
            (Path(directory) / "data").mkdir()
            (Path(directory) / "config" / "users.toml").write_text(USERS_TOML)
            (Path(directory) / "config" / "firmware.toml").write_text(FIRMWARE_TOML)
            result = self.run_scenario(directory, SCRIPT)
            self.assertIn("OK", result.stdout, result.stdout + result.stderr)

    def test_users_added_to_config_are_synced_into_existing_db(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config").mkdir()
            config = Path(directory) / "config" / "users.toml"
            config.write_text('[lecturers]\nlecturer1 = { password = "pw1", group = "group1" }\n')
            seed = self.run_scenario(directory, "import simple_auth; print('OK')")
            self.assertIn("OK", seed.stdout, seed.stdout + seed.stderr)

            config.write_text(USERS_TOML)
            check = self.run_scenario(directory, textwrap.dedent("""
                from simple_auth import auth
                user = auth.authenticate_user('hlinsko1', 'pw2')
                assert user and user['group_id'] == 'hlinsko', user
                print('OK')
            """))
            self.assertIn("OK", check.stdout, check.stdout + check.stderr)


if __name__ == "__main__":
    unittest.main()
