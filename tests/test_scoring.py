import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

class _TestUserConfig:
    def get_board_display_name(self, board_id):
        return None


sys.modules.setdefault(
    "user_config",
    types.SimpleNamespace(get_user_config=lambda: _TestUserConfig()),
)

from MeritOrder import Power
from scoring import (
    calculate_final_scores,
    get_balance_score,
    get_ecology_score,
    get_finances_score,
    get_team_stats,
)
from state import BoardState


def round_data(board_id, production, consumption):
    return {
        board_id: {
            "productions": production,
            "total_consumption": consumption,
        }
    }


def test_stability_is_symmetric_and_decreases_towards_cutoff():
    history = [
        round_data("board1", [(Power.GAS, 1000)], 1000),
        round_data("board2", [(Power.GAS, 1001)], 1000),
        round_data("board3", [(Power.GAS, 1002)], 1000),
        round_data("board4", [(Power.GAS, 1005)], 1000),
        round_data("board5", [(Power.GAS, 1009)], 1000),
        round_data("board6", [(Power.GAS, 1010)], 1000),
        round_data("board7", [(Power.GAS, 995)], 1000),
    ]

    stats = get_team_stats(history)
    scores = [get_balance_score(stats, board_id) for board_id in stats]

    assert scores[0] == 1
    assert scores[1] == 1
    assert scores[2] > scores[3] > scores[4] > scores[5]
    assert scores[3] == scores[6]
    assert scores[5] == 0


def test_blackout_and_partial_service_are_penalized():
    blackout = calculate_final_scores([round_data("blackout", [], 100)])['blackout']
    partial = calculate_final_scores([
        round_data("partial", [(Power.WIND, 50)], 100)
    ])['partial']

    assert blackout["ecology"] == 0
    assert blackout["finances"] == 0
    assert blackout["stability"] == 0
    assert partial["ecology"] == 50
    assert partial["finances"] == 50


def test_fully_served_source_scores_use_cost_and_emissions():
    renewable = calculate_final_scores([
        round_data("renewable", [(Power.WIND, 100)], 100)
    ])['renewable']
    coal = calculate_final_scores([
        round_data("coal", [(Power.COAL, 100)], 100)
    ])['coal']
    gas = calculate_final_scores([
        round_data("gas", [(Power.GAS, 100)], 100)
    ])['gas']

    assert renewable["ecology"] == 100
    assert renewable["finances"] == 100
    assert coal["ecology"] == 0
    assert coal["finances"] == round(100 * (1 - 101 / 132), 2)
    assert gas["ecology"] == 50
    assert gas["finances"] == 0
    assert gas["popularity"] == 62.5


def test_development_uses_only_the_common_final_round():
    history = [
        {
            **round_data("board1", [(Power.WIND, 1000)], 1000),
            **round_data("board2", [(Power.WIND, 100)], 100),
        },
        {
            **round_data("board1", [(Power.WIND, 500)], 500),
            **round_data("board2", [(Power.WIND, 1000)], 1000),
        },
    ]

    scores = calculate_final_scores(history)

    assert scores["board1"]["development"] == 50
    assert scores["board2"]["development"] == 100
    assert scores["board2"]["popularity"] == 100


def test_development_ties_and_all_zero_consumption():
    tied = calculate_final_scores([
        {
            **round_data("board1", [(Power.WIND, 100)], 100),
            **round_data("board2", [(Power.WIND, 100)], 100),
        }
    ])
    assert tied["board1"]["development"] == 100
    assert tied["board2"]["development"] == 100

    assert calculate_final_scores([
        {
            **round_data("board1", [], 0),
            **round_data("board2", [], 0),
        }
    ]) == {}


def test_duplicate_display_names_do_not_collide_in_scoring():
    scores = calculate_final_scores([
        {
            **round_data("board1", [(Power.WIND, 100)], 100),
            **round_data("board2", [(Power.COAL, 100)], 100),
        }
    ])

    assert set(scores) == {"board1", "board2"}
    assert scores["board1"]["ecology"] > scores["board2"]["ecology"]


def test_empty_history_returns_no_scores():
    assert calculate_final_scores([]) == {}


def test_finalizing_a_round_is_idempotent():
    board = BoardState("board1")
    board.current_round_index = 4
    board.production = 100
    board.consumption = 100

    board.finalize_current_round()
    board.finalize_current_round()

    assert board.round_history == [4]
    assert board.production_history == [100]
    assert board.consumption_history == [100]
