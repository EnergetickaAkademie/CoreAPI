"""Custom (block editor) scenarios: compiler, export round-trip and API ownership."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from enak.Enak import Building, PlayRound, Slide, SlideRange, Source  # noqa: E402
from scenario_compiler import CITY_CENTER_NAMES, compile_document, export_script, new_document, validate  # noqa: E402
from state import available_script_generators  # noqa: E402


def snapshot(script):
    """Everything the game loop reads from a script, in comparable form."""
    rounds = []
    for rnd in script.getRounds():
        item = {"type": rnd.getType().name, "comment": rnd.getComment()}
        if isinstance(rnd, PlayRound):
            item.update(
                weather=[w.name for w in rnd.weather],
                outages=sorted(s.name for s in rnd.getOutages()),
                coefficients={s.name: v for s, v in rnd.production_coefficients.items()},
                modifiers={b.name: v for b, v in rnd.building_modifiers.items()},
                buildings_comment=rnd.getBuildingsComment(),
            )
        elif isinstance(rnd, SlideRange):
            item["slides"] = rnd.getSlides()
        elif isinstance(rnd, Slide):
            item["slide"] = rnd.getSlide()
        rounds.append(item)
    return {
        "rounds": rounds,
        "registered": {k: sorted(s.name for s in v) for k, v in script.registered_sources_by_round.items()},
        "changes": {k: [(b.name, d, n) for b, d, n in v] for k, v in script.building_changes.items()},
        "sources": {s.name: tuple(v) for s, v in script.source_productions.items()},
    }


def minimal_document():
    document = new_document("Test")
    document["steps"] = [
        {"type": "allow_production", "source": "COAL"},
        {"type": "day", "name": "Den", "settings": [
            {"type": "weather", "weather": "SUNNY"},
            {"type": "outage", "source": "GAS"},
            {"type": "modifier", "buildings": ["CITY_CENTER_A", "CITY_CENTER_B"], "value": 100},
        ]},
        {"type": "change_consumption", "buildings": ["FACTORY"], "day": 50, "night": 20},
        {"type": "night", "name": "", "settings": [{"type": "weather", "weather": "WINDY"}]},
        {"type": "slide_range", "images": ["normal/03.svg", "normal/04.svg"]},
    ]
    return document


class CompilerTests(unittest.TestCase):
    def test_builtin_scenarios_survive_export_and_compile(self):
        for scenario_id, generator in available_script_generators.items():
            with self.subTest(scenario=scenario_id):
                original = generator()
                document = json.loads(json.dumps(export_script(original, scenario_id)))
                self.assertEqual(validate(document), [])
                self.assertEqual(snapshot(compile_document(document)), snapshot(original))

    def test_compiles_blocks_in_order(self):
        script = compile_document(minimal_document())
        rounds = script.getRounds()
        self.assertEqual([r.getType().name for r in rounds], ["DAY", "NIGHT", "SLIDE_RANGE"])
        day = rounds[0]
        self.assertEqual(day.getComment(), "Den")
        self.assertIn("GAS", [s.name for s in day.getOutages()])
        self.assertEqual(day.building_modifiers[Building.CITY_CENTER_A], 100)
        self.assertEqual(day.building_modifiers[Building.CITY_CENTER_C], 0)
        self.assertEqual(day.production_coefficients[Source.COAL], 1.0)
        self.assertEqual(day.production_coefficients[Source.GAS], 0.0)
        self.assertEqual(script.registered_sources_by_round, {0: {Source.COAL}})
        # Placed after the day round -> applied when the night round (index 1) starts.
        self.assertEqual(script.building_changes, {1: [(Building.FACTORY, 50, 20)]})

    @staticmethod
    def play(document):
        """Consumption of every building in each round, as the game sees it."""
        script = compile_document(document)
        rounds = []
        while script.step():
            rounds.append({b.name: script.getCurrentBuildingConsumption(b) for b in Building})
        return script, rounds

    @staticmethod
    def doc(steps):
        document = new_document("Test")
        document["steps"] = steps
        return document

    def test_permanent_change_applies_from_the_next_round(self):
        change = {"type": "change_consumption", "buildings": ["FACTORY"], "day": 50, "night": 20}
        _, rounds = self.play(self.doc([
            change,  # before the first round: must not be dropped
            {"type": "day", "name": "", "settings": []},
            change,  # after the day: must not change that day retroactively
            {"type": "night", "name": "", "settings": []},
            {"type": "day", "name": "", "settings": []},
        ]))
        self.assertEqual([r["FACTORY"] for r in rounds], [450, 400 + 40, 500])

    def test_set_consumption_reaches_exact_values(self):
        _, rounds = self.play(self.doc([
            {"type": "day", "name": "", "settings": []},
            {"type": "change_consumption", "buildings": ["FACTORY"], "day": 70, "night": 70},
            {"type": "set_consumption", "buildings": ["FACTORY", *CITY_CENTER_NAMES], "day": 700, "night": 300},
            {"type": "day", "name": "", "settings": []},
            {"type": "night", "name": "", "settings": []},
        ]))
        self.assertEqual(rounds[0]["FACTORY"], 400)
        for name in ["FACTORY", *CITY_CENTER_NAMES]:
            self.assertEqual(rounds[1][name], 700, name)
            self.assertEqual(rounds[2][name], 300, name)

    def test_set_round_consumption_only_affects_that_round(self):
        _, rounds = self.play(self.doc([
            {"type": "day", "name": "", "settings": [
                {"type": "modifier", "buildings": ["STADIUM"], "value": 100},
                {"type": "set_round_consumption", "buildings": ["STADIUM", "CITY_CENTER_A"], "value": 1000},
            ]},
            {"type": "night", "name": "", "settings": [
                {"type": "set_round_consumption", "buildings": ["STADIUM"], "value": 50},
            ]},
            {"type": "day", "name": "", "settings": []},
        ]))
        self.assertEqual(rounds[0]["STADIUM"], 1000)
        self.assertEqual(rounds[0]["CITY_CENTER_A"], 1000)
        self.assertEqual(rounds[1]["STADIUM"], 50)
        self.assertEqual(rounds[2]["STADIUM"], 250)

    def test_change_production_shifts_range_from_the_next_round(self):
        script = compile_document(self.doc([
            {"type": "allow_production", "source": "COAL"},
            {"type": "day", "name": "", "settings": []},
            {"type": "change_production", "source": "COAL", "min": 100, "max": 250},
            {"type": "night", "name": "", "settings": []},
        ]))
        ranges = []
        while script.step():
            ranges.append(script.getCurrentProductionRange(Source.COAL))
        self.assertEqual(ranges, [(500, 1000), (600, 1250)])

    def test_set_requires_base_value(self):
        document = self.doc([
            {"type": "set_consumption", "buildings": ["CITY_CENTER"], "day": 1, "night": 1},
            {"type": "day", "name": "", "settings": []},
        ])
        self.assertNotEqual(validate(document), [])

    def test_city_center_ranges_are_rolled(self):
        script = compile_document(minimal_document())
        for building, (day, night) in script.building_consumptions.items():
            if building.name.startswith("CITY_CENTER_"):
                self.assertTrue(550 <= day <= 620 and 350 <= night <= 400)

    def test_rejects_invalid_nesting_and_names(self):
        cases = {
            "sunny at night": {"type": "night", "settings": [{"type": "weather", "weather": "SUNNY"}]},
            "allow inside round": {"type": "day", "settings": [{"type": "allow_production", "source": "COAL"}]},
            "round inside round": {"type": "day", "settings": [{"type": "night", "settings": []}]},
            "unknown source": {"type": "allow_production", "source": "FUSION"},
            "unknown building": {"type": "change_consumption", "buildings": ["CASTLE"], "day": 1, "night": 1},
            "empty slide range": {"type": "slide_range", "images": []},
            "settings outside round": {"type": "weather", "weather": "WINDY"},
        }
        for label, step in cases.items():
            with self.subTest(case=label):
                document = minimal_document()
                document["steps"].append(step)
                self.assertNotEqual(validate(document), [])

    def test_requires_a_round_and_valid_ranges(self):
        document = minimal_document()
        document["steps"] = [{"type": "allow_production", "source": "COAL"}]
        self.assertNotEqual(validate(document), [])

        document = minimal_document()
        document["settings"]["source_productions"]["COAL"] = [1000, 500]
        self.assertNotEqual(validate(document), [])

    def test_image_check_is_applied(self):
        errors = validate(minimal_document(), image_exists=lambda path: path != "normal/04.svg")
        self.assertEqual([e["path"] for e in errors], ["steps[4].images[1]"])


USERS_TOML = """
[lecturers]
lecturer1 = { password = "pw1", name = "Lecturer 1", group = "group1" }
lecturer2 = { password = "pw2", name = "Lecturer 2", group = "group1" }

[boards]
board1 = { password = "b", ota_password = "o", name = "board1", group = "group1", display_name = "Tym 1", id = 1 }

[groups]
group1 = { name = "Primary", max_boards = 10 }
"""

FIRMWARE_TOML = """
[firmware]
github_repository = "example/firmware"
manifest_url = ""
github_token = ""
catalog_cache_seconds = 300
ota_port = 8080
direct_ota_cidrs = []
"""

API_SCRIPT = textwrap.dedent("""
    import io, json
    import main

    client = main.app.test_client()

    def login(username, password):
        response = client.post('/login', json={'username': username, 'password': password})
        assert response.status_code == 200, response.get_json()
        return {'Authorization': 'Bearer ' + response.get_json()['token']}

    a, b = login('lecturer1', 'pw1'), login('lecturer2', 'pw2')

    builtin = client.get('/scenarios', headers=a).get_json()['scenarios']
    assert builtin and all(s['builtin'] for s in builtin), builtin

    template = client.get('/scenarios/' + builtin[0]['id'] + '/document', headers=a)
    assert template.status_code == 200, template.get_json()
    document = template.get_json()['document']
    document['name'] = 'Moje kopie'

    png = b'\\x89PNG\\r\\n\\x1a\\n' + b'0' * 32
    upload = client.post('/scenario_assets', headers=a, content_type='multipart/form-data',
                         data={'file': (io.BytesIO(png), 'slide.png')})
    assert upload.status_code == 201, upload.get_json()
    path = upload.get_json()['path']
    document['steps'].append({'type': 'slide', 'image': path})

    bad_upload = client.post('/scenario_assets', headers=a, content_type='multipart/form-data',
                             data={'file': (io.BytesIO(b'<svg/>'), 'x.svg')})
    assert bad_upload.status_code == 400

    created = client.post('/custom_scenarios', json=document, headers=a)
    assert created.status_code == 201, created.get_json()
    custom_id = created.get_json()['id']

    invalid = dict(document, steps=[{'type': 'night', 'settings': [{'type': 'weather', 'weather': 'SUNNY'}]}])
    assert client.post('/custom_scenarios', json=invalid, headers=a).status_code == 400

    # lecturer2 cannot use lecturer1's upload either
    stolen = dict(document, name='Kradez')
    assert client.post('/custom_scenarios', json=stolen, headers=b).status_code == 400

    ids_a = [s['id'] for s in client.get('/scenarios', headers=a).get_json()['scenarios']]
    ids_b = [s['id'] for s in client.get('/scenarios', headers=b).get_json()['scenarios']]
    assert ids_a[-1] == custom_id and custom_id not in ids_b, (ids_a, ids_b)

    assert client.get('/scenarios/' + custom_id + '/document', headers=b).status_code == 404
    assert client.put('/custom_scenarios/' + custom_id, json=document, headers=b).status_code == 404
    assert client.delete('/custom_scenarios/' + custom_id, headers=b).status_code == 404
    assert client.post('/start_game', json={'scenario_id': custom_id}, headers=b).status_code == 400

    document['name'] = 'Prejmenovano'
    assert client.put('/custom_scenarios/' + custom_id, json=document, headers=a).status_code == 200

    assert client.get('/slide_file/' + path).status_code == 200
    assert client.get('/slide_file/uploads/../../etc/passwd').status_code in (403, 404)

    started = client.post('/start_game', json={'scenario_id': custom_id}, headers=a)
    assert started.status_code == 200, started.get_json()
    rounds = 0
    while True:
        step = client.post('/next_round', headers=a).get_json()
        if step['status'] == 'game_finished':
            break
        rounds += 1
        last = step
    assert rounds == len([s for s in document['steps'] if s['type'] in ('day', 'night', 'slide', 'slide_range')])
    assert last.get('slide') == path, last

    assert client.delete('/custom_scenarios/' + custom_id, headers=a).status_code == 200
    assert custom_id not in [s['id'] for s in client.get('/scenarios', headers=a).get_json()['scenarios']]
    print('OK')
""")


class CustomScenarioApiTests(unittest.TestCase):
    def test_crud_is_owner_isolated_and_playable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data").mkdir()
            (root / "config" / "users.toml").write_text(USERS_TOML)
            (root / "config" / "firmware.toml").write_text(FIRMWARE_TOML)
            env = dict(os.environ, PYTHONPATH=str(SRC), MQTT_ENABLED="false",
                       BOARD_STATE_DB_PATH=str(root / "data" / "state.db"),
                       FIRMWARE_STATE_DIR=str(root / "data" / "firmware"),
                       SCENARIO_DB_PATH=str(root / "data" / "scenarios.db"),
                       SCENARIO_UPLOADS_DIR=str(root / "data" / "uploads"))
            result = subprocess.run([sys.executable, "-c", API_SCRIPT], cwd=directory, env=env,
                                    capture_output=True, text=True, timeout=120)
            self.assertIn("OK", result.stdout, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
