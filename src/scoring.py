"""Final scoring for completed energy-management games."""

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Tuple

from MeritOrder import MeritOrder, Power


prices = {
    Power.COAL: 101,
    Power.GAS: 132,
    Power.NUCLEAR: 15,
    Power.WATER: 0,
    Power.WATER_STORAGE: 0,
    Power.WIND: 0,
    Power.PHOTOVOLTAIC: 0,
    Power.BATTERY: 0,
}

co2eq = {
    Power.COAL: 1,
    Power.GAS: 0.5,
    Power.NUCLEAR: 0,
    Power.WATER: 0,
    Power.WATER_STORAGE: 0,
    Power.WIND: 0,
    Power.PHOTOVOLTAIC: 0,
    Power.BATTERY: 0,
}

BALANCE_CUTOFF_PERCENT = 1
BALANCE_DEADBAND_MW = 1


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _positive_productions(productions: Iterable[Tuple[Power, float]]) -> List[Tuple[Power, float]]:
    return [(power, amount) for power, amount in productions if amount > 0]


def _production_total(productions: Iterable[Tuple[Power, float]]) -> float:
    return sum(amount for _, amount in _positive_productions(productions))


def get_team_stats(history: List[Mapping[str, Mapping]]) -> Dict[str, Dict[str, list]]:
    team_stats = defaultdict(lambda: {
        "productions": [],
        "consumptions": [],
        "round_indices": [],
    })

    for round_data in history:
        for board_id, data in round_data.items():
            team_stats[board_id]["productions"].append(data["productions"])
            team_stats[board_id]["consumptions"].append(data["total_consumption"])
            team_stats[board_id]["round_indices"].append(data.get("round_index"))

    return dict(team_stats)


def get_num_rounds(history: List[Mapping]) -> int:
    return len(history)


def get_teams(history: List[Mapping]) -> List[str]:
    teams = []
    for round_data in history:
        for team in round_data:
            if team not in teams:
                teams.append(team)
    return teams


def get_total_consumption(team_stats: Mapping, team: str) -> float:
    return sum(max(0.0, value) for value in team_stats[team]["consumptions"])


def get_last_building_consumption(team_stats: Mapping, team: str) -> float:
    consumptions = team_stats[team]["consumptions"]
    return consumptions[-1] if consumptions else 0.0


def _round_cost_and_emissions(productions, consumption: float) -> Tuple[float, float, float]:
    demand = max(0.0, consumption)
    clean_productions = _positive_productions(productions)
    available = _production_total(clean_productions)
    served = min(available, demand)
    merit_order = MeritOrder(prices, clean_productions, demand)
    return merit_order.getTotalExpenses(), merit_order.getReleasedCO2(), served


def get_expenses(team_stats: Mapping, team: str) -> float:
    return sum(
        _round_cost_and_emissions(productions, consumption)[0]
        for productions, consumption in zip(
            team_stats[team]["productions"], team_stats[team]["consumptions"]
        )
    )


def get_co2(team_stats: Mapping, team: str) -> float:
    return sum(
        _round_cost_and_emissions(productions, consumption)[1]
        for productions, consumption in zip(
            team_stats[team]["productions"], team_stats[team]["consumptions"]
        )
    )


def _served_and_demand(team_stats: Mapping, team: str) -> Tuple[float, float]:
    demand = 0.0
    served = 0.0
    for productions, consumption in zip(
        team_stats[team]["productions"], team_stats[team]["consumptions"]
    ):
        round_demand = max(0.0, consumption)
        demand += round_demand
        served += min(_production_total(productions), round_demand)
    return served, demand


def get_ecology_score(team_stats: Mapping, team: str) -> float:
    served, demand = _served_and_demand(team_stats, team)
    if demand <= 0 or served <= 0:
        return 0.0

    emissions = get_co2(team_stats, team)
    quality = 1 - emissions / (co2eq[Power.COAL] * served)
    return _clamp(100 * (served / demand) * quality)


def get_finances_score(team_stats: Mapping, team: str) -> float:
    served, demand = _served_and_demand(team_stats, team)
    if demand <= 0 or served <= 0:
        return 0.0

    expenses = get_expenses(team_stats, team)
    quality = 1 - expenses / (prices[Power.GAS] * served)
    return _clamp(100 * (served / demand) * quality)


def get_prod_sums(productions: List[List[Tuple[Power, float]]]) -> List[float]:
    return [_production_total(round_productions) for round_productions in productions]


def get_prod_diffs(team_stats: Mapping, team: str):
    consumptions = team_stats[team]["consumptions"]
    productions = get_prod_sums(team_stats[team]["productions"])
    return [consumption - production for consumption, production in zip(consumptions, productions)], consumptions, productions


def _stability_fraction(production: float, consumption: float) -> float:
    demand = max(0.0, consumption)
    error = abs(demand - production)
    cutoff = BALANCE_CUTOFF_PERCENT * 0.01 * demand

    if error <= BALANCE_DEADBAND_MW:
        return 1.0
    if cutoff <= BALANCE_DEADBAND_MW or error >= cutoff:
        return 0.0
    return _clamp((cutoff - error) / (cutoff - BALANCE_DEADBAND_MW), 0.0, 1.0)


def get_balance(team_stats: Mapping, team: str, num_rounds: int = None) -> List[float]:
    return [
        _stability_fraction(production, consumption)
        for production, consumption in zip(
            get_prod_sums(team_stats[team]["productions"]),
            team_stats[team]["consumptions"],
        )
    ]


def get_balance_score(team_stats: Mapping, team: str, num_rounds: int = None) -> float:
    balance = get_balance(team_stats, team, num_rounds)
    return sum(balance) / len(balance) if balance else 0.0


def get_development_scores(history: List[Mapping], team_stats: Mapping) -> Dict[str, float]:
    if not history:
        return {team: 0.0 for team in team_stats}

    final_round = history[-1]
    final_consumptions = {
        team: max(0.0, data.get("total_consumption", 0.0))
        for team, data in final_round.items()
    }
    highest_consumption = max(final_consumptions.values(), default=0.0)

    if highest_consumption <= 0:
        return {team: 0.0 for team in team_stats}

    return {
        team: _clamp(100 * final_consumptions.get(team, 0.0) / highest_consumption)
        for team in team_stats
    }


def get_building_popularity(team_stats: Mapping, team: str, development_scores: Mapping[str, float] = None) -> float:
    if development_scores is None:
        development_scores = {team: 0.0}
    return development_scores.get(team, 0.0)


def get_scores(team_stats: Mapping, team: str, num_rounds: int = None, development_scores: Mapping[str, float] = None) -> Dict[str, float]:
    ecology = get_ecology_score(team_stats, team)
    finances = get_finances_score(team_stats, team)
    stability = 100 * get_balance_score(team_stats, team, num_rounds)
    development = get_building_popularity(team_stats, team, development_scores)
    popularity = (stability + finances + ecology + development) / 4

    return {
        "ecology": round(_clamp(ecology), 2),
        "finances": round(_clamp(finances), 2),
        "stability": round(_clamp(stability), 2),
        "development": round(_clamp(development), 2),
        "popularity": round(_clamp(popularity), 2),
    }


def calculate_final_scores(history: List[Mapping]) -> Dict[str, Dict[str, float]]:
    if not history:
        return {}

    team_stats = get_team_stats(history)
    development_scores = get_development_scores(history, team_stats)
    scores = {}

    for team in get_teams(history):
        if get_total_consumption(team_stats, team) <= 0:
            continue
        scores[team] = get_scores(team_stats, team, len(history), development_scores)

    return scores
