"""Declarative custom scenarios.

A custom scenario is stored as a JSON "scenario document" (built in the
block editor of the frontend). This module

* validates such a document (``validate``),
* compiles it into an ``Enak.Script`` by replaying exactly the same calls a
  hand-written scenario in ``scenarios/*.py`` would make (``compile_document``),
* exports an existing ``Script`` (the built-in Python scenarios) back into a
  document so it can be used as a template in the editor (``export_script``).

No user supplied code is ever executed.

Document format (version 1)::

    {
      "version": 1,
      "name": "...",
      "settings": {
        "building_consumptions": {"FACTORY": {"day": [400, 400], "night": [400, 400]}, ...},
        "source_productions": {"COAL": [500, 1000], ...}
      },
      "steps": [
        {"type": "allow_production", "source": "COAL"},
        {"type": "change_consumption", "buildings": ["CITY_CENTER_A"], "day": 120, "night": 60},
        {"type": "set_consumption", "buildings": ["FACTORY"], "day": 500, "night": 300},
        {"type": "change_production", "source": "COAL", "min": 100, "max": 200},
        {"type": "day" | "night", "name": "...", "settings": [
            {"type": "weather", "weather": "SUNNY"},
            {"type": "outage", "source": "GAS"},
            {"type": "modifier", "buildings": ["STADIUM"], "value": 600},
            {"type": "set_round_consumption", "buildings": ["STADIUM"], "value": 900},
            {"type": "buildings_comment", "text": "..."},
            {"type": "coefficient", "source": "WIND", "value": 0.5}
        ]},
        {"type": "slide", "image": "normal/12.svg"},
        {"type": "slide_range", "images": ["normal/29.svg", "uploads/<owner>/<file>.png"]}
      ]
    }

Building consumptions are ``[min, max]`` ranges; a random integer is drawn
from each range every time a game is started (like ``randint`` in the Python
scenarios). ``min == max`` gives a fixed value.

Timing of permanent changes: a ``change_consumption`` / ``set_consumption`` /
``change_production`` block placed before round N takes effect from round N.
(Enak's own ``changeBuildingConsumption`` attaches the change to the round
*before* the call, which applies it one round early and silently drops
changes made before the first round; the compiler writes the change tables
directly to avoid that.)

``set_*`` blocks have no Enak equivalent; they are compiled into the change
needed to reach the given value, based on the consumption the compiler tracks
(the values rolled for this game plus all earlier changes).
"""

from __future__ import annotations

import random
from typing import Any, Callable, Dict, List, Optional

from enak.Enak import (
    Building,
    CITY_CENTERS,
    Day,
    Night,
    PlayRound,
    RoundType,
    Script,
    Slide,
    SlideRange,
    Source,
    WeatherType,
)

DOCUMENT_VERSION = 1

MAX_STEPS = 500
MAX_SETTINGS_PER_ROUND = 100
MAX_SLIDES_PER_RANGE = 100
MAX_TEXT_LENGTH = 300
MAX_NAME_LENGTH = 100
MAX_ABS_POWER = 100_000
MAX_ABS_COEFFICIENT = 100.0

# Weather builder method for every weather type, per round type. Night has no
# sunny() in the Enak API, so SUNNY is day-only.
WEATHER_METHODS: Dict[str, str] = {
    "SUNNY": "sunny",
    "PARTLY_CLOUDY": "partly_cloudy",
    "CLOUDY": "cloudy",
    "RAINY": "rainy",
    "FOGGY": "foggy",
    "SNOWY": "snowy",
    "WINDY": "windy",
    "BREEZY": "breezy",
    "CALM": "calm",
}
DAY_WEATHER = set(WEATHER_METHODS)
NIGHT_WEATHER = DAY_WEATHER - {"SUNNY"}

# Sources whose coefficient is set as a side effect of a weather type.
WEATHER_AFFECTED_SOURCE = {
    WeatherType.SUNNY: Source.PHOTOVOLTAIC,
    WeatherType.PARTLY_CLOUDY: Source.PHOTOVOLTAIC,
    WeatherType.CLOUDY: Source.PHOTOVOLTAIC,
    WeatherType.SNOWY: Source.PHOTOVOLTAIC,
    WeatherType.CALM: Source.WIND,
    WeatherType.BREEZY: Source.WIND,
    WeatherType.WINDY: Source.WIND,
}

BUILDING_NAMES = {b.name for b in Building}
SOURCE_NAMES = {s.name for s in Source}
CITY_CENTER_NAMES = [b.name for b in CITY_CENTERS]

ROUND_SETTING_TYPES = {"weather", "outage", "modifier", "set_round_consumption", "buildings_comment", "coefficient"}
STEP_TYPES = {"allow_production", "change_consumption", "set_consumption", "change_production",
              "day", "night", "slide", "slide_range"}

# Default random range used for city centers (same as the Python scenarios).
CITY_CENTER_DAY_RANGE = [550, 620]
CITY_CENTER_NIGHT_RANGE = [350, 400]


def default_settings() -> Dict[str, Any]:
    """Base values for a new blank scenario (taken from scenarios/normal.py)."""
    buildings: Dict[str, Any] = {
        name: {"day": list(CITY_CENTER_DAY_RANGE), "night": list(CITY_CENTER_NIGHT_RANGE)}
        for name in CITY_CENTER_NAMES
    }
    fixed = {
        "FACTORY": (400, 400),
        "STADIUM": (250, 400),
        "HOSPITAL": (350, 250),
        "UNIVERSITY": (400, 200),
        "AIRPORT": (500, 400),
        "SHOPPING_MALL": (350, 200),
        "TECHNOLOGY_CENTER": (300, 250),
        "FARM": (80, 40),
        "LIVING_QUARTER_SMALL": (70, 40),
        "LIVING_QUARTER_LARGE": (100, 60),
        "SCHOOL": (80, 30),
    }
    for name, (day, night) in fixed.items():
        buildings[name] = {"day": [day, day], "night": [night, night]}

    return {
        "building_consumptions": buildings,
        "source_productions": {
            "COAL": [500, 1000],
            "HYDRO": [0, 200],
            "HYDRO_STORAGE": [-200, 200],
            "GAS": [0, 500],
            "NUCLEAR": [900, 1000],
            "WIND": [0, 100],
            "PHOTOVOLTAIC": [0, 100],
            "BATTERY": [-200, 200],
        },
    }


def new_document(name: str = "Nový scénář") -> Dict[str, Any]:
    return {"version": DOCUMENT_VERSION, "name": name, "settings": default_settings(), "steps": []}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _Validator:
    def __init__(self, image_exists: Optional[Callable[[str], bool]]):
        self.errors: List[Dict[str, str]] = []
        self.image_exists = image_exists
        self.known_buildings: set = set()

    def error(self, path: str, message: str):
        self.errors.append({"path": path, "message": message})

    def text(self, value: Any, path: str, max_length: int = MAX_TEXT_LENGTH, required: bool = False):
        if value is None or value == "":
            if required:
                self.error(path, "Hodnota je povinná.")
            return
        if not isinstance(value, str):
            self.error(path, "Hodnota musí být text.")
        elif len(value) > max_length:
            self.error(path, f"Text může mít nejvýše {max_length} znaků.")

    def power(self, value: Any, path: str):
        if not _is_int(value):
            self.error(path, "Hodnota musí být celé číslo.")
        elif abs(value) > MAX_ABS_POWER:
            self.error(path, f"Hodnota musí být v rozsahu ±{MAX_ABS_POWER}.")

    def power_range(self, value: Any, path: str):
        if not isinstance(value, list) or len(value) != 2:
            self.error(path, "Rozsah musí mít tvar [min, max].")
            return
        self.power(value[0], f"{path}[0]")
        self.power(value[1], f"{path}[1]")
        if _is_int(value[0]) and _is_int(value[1]) and value[0] > value[1]:
            self.error(path, "Minimum nesmí být větší než maximum.")

    def source(self, value: Any, path: str):
        if value not in SOURCE_NAMES:
            self.error(path, f"Neznámý zdroj: {value!r}.")

    def buildings(self, value: Any, path: str):
        if not isinstance(value, list) or not value:
            self.error(path, "Seznam budov nesmí být prázdný.")
            return
        for i, name in enumerate(value):
            if name not in BUILDING_NAMES:
                self.error(f"{path}[{i}]", f"Neznámá budova: {name!r}.")

    def buildings_with_base(self, value: Any, path: str):
        """Buildings whose consumption is *set* need a base value to start from."""
        self.buildings(value, path)
        if isinstance(value, list):
            for i, name in enumerate(value):
                if name in BUILDING_NAMES and name not in self.known_buildings:
                    self.error(f"{path}[{i}]", f"Budova {name} nemá základní spotřebu.")

    def non_negative_power(self, value: Any, path: str):
        self.power(value, path)
        if _is_int(value) and value < 0:
            self.error(path, "Spotřeba nesmí být záporná.")

    def image(self, value: Any, path: str):
        if not isinstance(value, str) or not value:
            self.error(path, "Chybí obrázek.")
            return
        if self.image_exists is not None and not self.image_exists(value):
            self.error(path, f"Obrázek {value!r} neexistuje.")

    def settings(self, settings: Any):
        if not isinstance(settings, dict):
            self.error("settings", "Chybí základní hodnoty.")
            return
        buildings = settings.get("building_consumptions")
        if not isinstance(buildings, dict):
            self.error("settings.building_consumptions", "Chybí spotřeby budov.")
        else:
            for name, value in buildings.items():
                path = f"settings.building_consumptions.{name}"
                if name not in BUILDING_NAMES:
                    self.error(path, f"Neznámá budova: {name!r}.")
                    continue
                if not isinstance(value, dict):
                    self.error(path, "Spotřeba musí obsahovat den a noc.")
                    continue
                self.power_range(value.get("day"), f"{path}.day")
                self.power_range(value.get("night"), f"{path}.night")
                self.known_buildings.add(name)
        sources = settings.get("source_productions")
        if not isinstance(sources, dict):
            self.error("settings.source_productions", "Chybí výkony zdrojů.")
        else:
            for name, value in sources.items():
                path = f"settings.source_productions.{name}"
                if name not in SOURCE_NAMES:
                    self.error(path, f"Neznámý zdroj: {name!r}.")
                    continue
                self.power_range(value, path)

    def round_setting(self, setting: Any, path: str, round_type: str):
        if not isinstance(setting, dict):
            self.error(path, "Neplatný blok.")
            return
        kind = setting.get("type")
        if kind not in ROUND_SETTING_TYPES:
            self.error(path, f"Blok {kind!r} nelze vložit do kola.")
            return
        if kind == "weather":
            allowed = DAY_WEATHER if round_type == "day" else NIGHT_WEATHER
            if setting.get("weather") not in allowed:
                self.error(path, f"Počasí {setting.get('weather')!r} nelze použít v tomto kole.")
        elif kind == "outage":
            self.source(setting.get("source"), f"{path}.source")
        elif kind == "modifier":
            self.buildings(setting.get("buildings"), f"{path}.buildings")
            self.power(setting.get("value"), f"{path}.value")
        elif kind == "set_round_consumption":
            self.buildings_with_base(setting.get("buildings"), f"{path}.buildings")
            self.non_negative_power(setting.get("value"), f"{path}.value")
        elif kind == "buildings_comment":
            self.text(setting.get("text"), f"{path}.text", required=True)
        elif kind == "coefficient":
            self.source(setting.get("source"), f"{path}.source")
            value = setting.get("value")
            if not _is_number(value) or abs(value) > MAX_ABS_COEFFICIENT:
                self.error(f"{path}.value", "Koeficient musí být číslo.")

    def step(self, step: Any, path: str):
        if not isinstance(step, dict):
            self.error(path, "Neplatný blok.")
            return
        kind = step.get("type")
        if kind not in STEP_TYPES:
            self.error(path, f"Blok {kind!r} nelze umístit mezi kola.")
            return
        if kind == "allow_production":
            self.source(step.get("source"), f"{path}.source")
        elif kind == "change_consumption":
            self.buildings(step.get("buildings"), f"{path}.buildings")
            self.power(step.get("day"), f"{path}.day")
            self.power(step.get("night"), f"{path}.night")
        elif kind == "set_consumption":
            self.buildings_with_base(step.get("buildings"), f"{path}.buildings")
            self.non_negative_power(step.get("day"), f"{path}.day")
            self.non_negative_power(step.get("night"), f"{path}.night")
        elif kind == "change_production":
            self.source(step.get("source"), f"{path}.source")
            self.power(step.get("min"), f"{path}.min")
            self.power(step.get("max"), f"{path}.max")
        elif kind in ("day", "night"):
            self.text(step.get("name"), f"{path}.name")
            settings = step.get("settings", [])
            if not isinstance(settings, list):
                self.error(f"{path}.settings", "Nastavení kola musí být seznam.")
                return
            if len(settings) > MAX_SETTINGS_PER_ROUND:
                self.error(f"{path}.settings", "Kolo obsahuje příliš mnoho bloků.")
            for i, setting in enumerate(settings):
                self.round_setting(setting, f"{path}.settings[{i}]", kind)
        elif kind == "slide":
            self.image(step.get("image"), f"{path}.image")
        elif kind == "slide_range":
            images = step.get("images")
            if not isinstance(images, list) or not images:
                self.error(f"{path}.images", "Prezentace musí obsahovat alespoň jeden obrázek.")
                return
            if len(images) > MAX_SLIDES_PER_RANGE:
                self.error(f"{path}.images", "Prezentace obsahuje příliš mnoho obrázků.")
            for i, image in enumerate(images):
                self.image(image, f"{path}.images[{i}]")


def validate(document: Any, image_exists: Optional[Callable[[str], bool]] = None) -> List[Dict[str, str]]:
    """Return a list of ``{"path", "message"}`` errors; empty when valid.

    ``image_exists`` is called for each slide image path; when omitted, image
    paths are only checked for being non-empty strings.
    """
    v = _Validator(image_exists)
    if not isinstance(document, dict):
        v.error("", "Scénář musí být objekt.")
        return v.errors
    if document.get("version", DOCUMENT_VERSION) != DOCUMENT_VERSION:
        v.error("version", "Nepodporovaná verze scénáře.")
    v.text(document.get("name"), "name", max_length=MAX_NAME_LENGTH, required=True)
    v.settings(document.get("settings"))

    steps = document.get("steps")
    if not isinstance(steps, list):
        v.error("steps", "Scénář musí obsahovat seznam kroků.")
        return v.errors
    if len(steps) > MAX_STEPS:
        v.error("steps", f"Scénář může mít nejvýše {MAX_STEPS} bloků.")
    for i, step in enumerate(steps):
        v.step(step, f"steps[{i}]")
    if not any(isinstance(s, dict) and s.get("type") in ("day", "night", "slide", "slide_range") for s in steps):
        v.error("steps", "Scénář musí obsahovat alespoň jedno kolo.")
    return v.errors


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def _roll(value_range: List[int], rng: random.Random) -> int:
    low, high = value_range
    return low if low == high else rng.randint(low, high)


def compile_document(document: Dict[str, Any], rng: Optional[random.Random] = None) -> Script:
    """Build a fresh ``Script`` from a (validated) document."""
    errors = validate(document)
    if errors:
        raise ValueError("; ".join(f"{e['path']}: {e['message']}" for e in errors))

    rng = rng or random.Random()
    settings = document["settings"]

    building_consumptions = {
        Building[name]: (_roll(value["day"], rng), _roll(value["night"], rng))
        for name, value in settings["building_consumptions"].items()
    }
    source_productions = {
        Source[name]: tuple(value) for name, value in settings["source_productions"].items()
    }
    # Every source must have a range, otherwise boards get no limits for it.
    for source in Source:
        source_productions.setdefault(source, (0, 0))

    script = Script(building_consumptions, source_productions)
    # Consumption (day, night) each building will have from the next round on.
    current = dict(building_consumptions)

    def change_consumption(building: Building, day: int, night: int):
        if building not in current:
            return
        # Keyed by the index of the next round: applied when that round starts.
        script.building_changes.setdefault(len(script.rounds), []).append((building, day, night))
        old_day, old_night = current[building]
        current[building] = (old_day + day, old_night + night)

    for step in document["steps"]:
        kind = step["type"]
        if kind == "allow_production":
            script.allowProduction(Source[step["source"]])
        elif kind == "change_consumption":
            for name in step["buildings"]:
                change_consumption(Building[name], step["day"], step["night"])
        elif kind == "set_consumption":
            for name in step["buildings"]:
                building = Building[name]
                if building in current:
                    day, night = current[building]
                    if (day, night) != (step["day"], step["night"]):
                        change_consumption(building, step["day"] - day, step["night"] - night)
        elif kind == "change_production":
            script.production_changes.setdefault(len(script.rounds), []).append(
                (Source[step["source"]], step["min"], step["max"])
            )
        elif kind in ("day", "night"):
            builder = Day() if kind == "day" else Night()
            if step.get("name"):
                builder.comment(step["name"])
            for setting in step.get("settings", []):
                _apply_round_setting(builder, setting, current, 0 if kind == "day" else 1)
            script.addRound(builder.build())
        elif kind == "slide":
            script.addRound(Slide(step["image"]))
        elif kind == "slide_range":
            script.addRound(SlideRange(list(step["images"])))

    return script


def _apply_round_setting(builder, setting: Dict[str, Any], current: Dict[Building, tuple], period: int):
    kind = setting["type"]
    if kind == "weather":
        getattr(builder, WEATHER_METHODS[setting["weather"]])()
    elif kind == "outage":
        builder.outage(Source[setting["source"]])
    elif kind == "modifier":
        buildings = [Building[name] for name in setting["buildings"]]
        if len(buildings) == 1:
            builder.addBuildingModifier(buildings[0], setting["value"])
        else:
            builder.addBuildingModifiers(buildings, setting["value"])
    elif kind == "set_round_consumption":
        # Modifier that brings this round's consumption to exactly the value,
        # taking into account modifiers added earlier in the same round.
        modifiers = builder.round.building_modifiers
        for name in setting["buildings"]:
            building = Building[name]
            if building in current:
                needed = setting["value"] - current[building][period] - modifiers[building]
                builder.addBuildingModifier(building, needed)
    elif kind == "buildings_comment":
        builder.buildings_comment(setting["text"])
    elif kind == "coefficient":
        builder.setCoefficient(Source[setting["source"]], float(setting["value"]))


# ---------------------------------------------------------------------------
# Export (built-in Script -> document)
# ---------------------------------------------------------------------------

def _number(value: float):
    return int(value) if float(value).is_integer() else value


def _export_settings(script: Script) -> Dict[str, Any]:
    buildings: Dict[str, Any] = {}
    for building, (day, night) in script.building_consumptions.items():
        if (
            building in CITY_CENTERS
            and CITY_CENTER_DAY_RANGE[0] <= day <= CITY_CENTER_DAY_RANGE[1]
            and CITY_CENTER_NIGHT_RANGE[0] <= night <= CITY_CENTER_NIGHT_RANGE[1]
        ):
            # Built-in scenarios roll city centers with randint(); keep them random.
            buildings[building.name] = {"day": list(CITY_CENTER_DAY_RANGE), "night": list(CITY_CENTER_NIGHT_RANGE)}
        else:
            buildings[building.name] = {"day": [_number(day)] * 2, "night": [_number(night)] * 2}
    sources = {
        source.name: [_number(low), _number(high)]
        for source, (low, high) in script.source_productions.items()
    }
    return {"building_consumptions": buildings, "source_productions": sources}


def _export_round(rnd: PlayRound, master: Dict[Source, float]) -> Dict[str, Any]:
    kind = "day" if rnd.getRoundType() == RoundType.DAY else "night"
    settings: List[Dict[str, Any]] = []

    for weather in rnd.getWeather() or []:
        settings.append({"type": "weather", "weather": weather.name})
    for source in rnd.outages:
        settings.append({"type": "outage", "source": source.name})

    # Group identical modifiers into one multi-building block.
    groups: Dict[float, List[Building]] = {}
    for building, value in rnd.building_modifiers.items():
        if value:
            groups.setdefault(value, []).append(building)
    for value, buildings in groups.items():
        settings.append({"type": "modifier", "buildings": [b.name for b in buildings], "value": _number(value)})

    # Explicit coefficients = changes not caused by weather/outages/night.
    implicit = {WEATHER_AFFECTED_SOURCE[w] for w in rnd.getWeather() or [] if w in WEATHER_AFFECTED_SOURCE}
    implicit.update(rnd.outages)
    if kind == "night":
        implicit.add(Source.PHOTOVOLTAIC)
    for source in sorted(rnd.production_changes - implicit, key=lambda s: s.value):
        if master.get(source):
            value = rnd.production_coefficients[source] / master[source]
            settings.append({"type": "coefficient", "source": source.name, "value": _number(value)})

    if rnd.getBuildingsComment():
        settings.append({"type": "buildings_comment", "text": rnd.getBuildingsComment()})

    step: Dict[str, Any] = {"type": kind, "name": rnd.getComment() or "", "settings": settings}
    return step


def _export_changes(changes) -> List[Dict[str, Any]]:
    """Group consecutive (building, day, night) changes with equal values."""
    steps: List[Dict[str, Any]] = []
    for building, day, night in changes:
        last = steps[-1] if steps else None
        if last and last["day"] == _number(day) and last["night"] == _number(night):
            last["buildings"].append(building.name)
        else:
            steps.append({"type": "change_consumption", "buildings": [building.name],
                          "day": _number(day), "night": _number(night)})
    return steps


def export_script(script: Script, name: str) -> Dict[str, Any]:
    """Convert an un-stepped ``Script`` into a scenario document."""
    steps: List[Dict[str, Any]] = []
    rounds = script.getRounds()

    # Master coefficients as they were when each round was added.
    master = {source: 0.0 for source in Source}

    def allows_before(index: int):
        for source in sorted(script.registered_sources_by_round.get(index, ()), key=lambda s: s.value):
            master[source] = 1.0
            steps.append({"type": "allow_production", "source": source.name})

    def production_changes_before(index: int):
        for source, low, high in script.production_changes.get(index, []):
            steps.append({"type": "change_production", "source": source.name,
                          "min": _number(low), "max": _number(high)})

    # Enak applies a change with key k when round k starts, i.e. it is in
    # effect from round k on -> place it right before round k. (Key -1 is
    # never applied by Enak; it is dropped.)
    for index, rnd in enumerate(rounds):
        allows_before(index)
        steps.extend(_export_changes(script.building_changes.get(index, [])))
        production_changes_before(index)
        if isinstance(rnd, PlayRound):
            steps.append(_export_round(rnd, master))
        elif isinstance(rnd, SlideRange):
            steps.append({"type": "slide_range", "images": list(rnd.getSlides())})
        elif isinstance(rnd, Slide):
            steps.append({"type": "slide", "image": rnd.getSlide()})
    allows_before(len(rounds))

    return {"version": DOCUMENT_VERSION, "name": name, "settings": _export_settings(script), "steps": steps}
