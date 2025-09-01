from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import time
import sys
import os

from enak import Enak, Script

from scenarios.demo import getScript
from scenarios.normal import normalScript
from scenarios.test import getScript as getTestScript


# Store script generator functions instead of instances
# This ensures we get fresh scripts for each game
available_script_generators: Dict[str, Callable[[], Script]] = {
    "demo": getScript,
    "test": getTestScript,
    "normal": normalScript
}

# Backwards compatibility - generate instances on demand
available_scripts: Dict[str, Script] = {}

def get_fresh_script(scenario_id: str) -> Script:
    """Get a fresh script instance for the given scenario"""
    if scenario_id in available_script_generators:
        return available_script_generators[scenario_id]()
    elif scenario_id in available_scripts:
        # Fallback for old-style scripts - manually reset state
        script = available_scripts[scenario_id]
        script.current_round_index = 0
        return script
    else:
        raise ValueError(f"Unknown scenario: {scenario_id}")

# Populate available_scripts for backwards compatibility
for scenario_id, generator in available_script_generators.items():
    available_scripts[scenario_id] = generator()

class GameState:
    """
    Represents the state of the game.
    """
    def __init__(self, script):
        self.boards: Dict[str, 'BoardState'] = {}
        self.script = script

    def get_script(self) -> Script:
        """
        Returns the script associated with the game state.
        """
        return self.script
    
    def register_board(self, board_id: str) -> 'BoardState':
        """
        Registers a new board in the game state.
        """
        print(f"Registering board: {board_id}", file=sys.stderr)
        if board_id not in self.boards:
            self.boards[board_id] = BoardState(board_id)
            print(f"Board {board_id} registered successfully.", file=sys.stderr)
        return self.boards[board_id]
    def get_board(self, board_id: str) -> Optional['BoardState']:
        """
        Retrieves the board state by ID.
        """
        print(f"Retrieving board: {board_id}", file=sys.stderr)
        print(self.boards, file=sys.stderr)
        if board_id in self.boards:
            return self.boards[board_id]
        raise KeyError(f"Board with ID {board_id} not found in game state.")

    def finalize_all_boards_current_round(self):
        """
        Finalize the current round for all boards.
        This should be called when the game ends or when transitioning rounds.
        """
        for board in self.boards.values():
            board.finalize_current_round()
            board.clear_connected_buildings()  # Clear buildings when game/scenario ends
            
    def get_all_boards_history_summary(self) -> Dict[str, Dict]:
        """
        Get a summary of all boards' history data.
        """
        summary = {}
        for board_id, board in self.boards.items():
            summary[board_id] = {
                'round_count': len(board.round_history),
                'rounds': board.round_history.copy(),
                'latest_production': board.production,
                'latest_consumption': board.consumption,
                'current_round_index': board.current_round_index
            }
        return summary

    def get_connection_summary(self) -> Dict[str, any]:
        """
        Get a summary of board connection status.
        """
        connected_boards = []
        disconnected_boards = []
        
        for board_id, board in self.boards.items():
            board_info = {
                'board_id': board_id,
                'display_name': board.display_name,
                'time_since_update': board.time_since_last_update()
            }
            
            if board.is_connected():
                connected_boards.append(board_info)
            else:
                board_info['last_updated'] = board.last_updated
                disconnected_boards.append(board_info)
        
        return {
            'total_boards': len(self.boards),
            'connected_count': len(connected_boards),
            'disconnected_count': len(disconnected_boards),
            'connected_boards': connected_boards,
            'disconnected_boards': disconnected_boards
        }


class BoardState:
    """
    Represents the state of a board in the application.
    """
    # Connection timeout in seconds
    CONNECTION_TIMEOUT = 5.0
    
    @staticmethod
    def generate_display_name(board_id: str) -> str:
        """
        Generate a consistent, user-friendly display name for a board.
        This ensures boards keep the same name when they reconnect.
        """
        if board_id.startswith('board'):
            try:
                # Extract number from board_id like 'board1' -> '1'
                board_number = board_id[5:]  # Remove 'board' prefix
                return f"Team {board_number}"
            except (ValueError, IndexError):
                # Fallback if parsing fails
                return f"Team {board_id}"
        else:
            # For non-standard board IDs, use the ID directly with Team prefix
            return f"Team {board_id}"
    
    def __init__(self, id: str):
        self.id = id
        self.display_name = self.generate_display_name(id)
        self.production: int = 0
        self.consumption: int = 0
        self.last_updated: float = time.time()
        self.connected_consumption: List[int] = []
        self.connected_production: List[int] = []
        # History tracking for statistics - now by round
        self.production_history: List[int] = []  # Final values from each completed round
        self.consumption_history: List[int] = []  # Final values from each completed round
        self.round_history: List[int] = []  # Round indices corresponding to history entries
        # Track current round to detect round changes
        self.current_round_index: int = -1
        # Power generation by type tracking
        self.power_generation_by_type: Dict[str, float] = {}
        # Connected buildings for persistence across board restarts
        self.connected_buildings: List[Dict[str, Any]] = []

    def is_connected(self) -> bool:
        """
        Check if the board is considered connected based on last update time.
        Returns False if the board hasn't updated within CONNECTION_TIMEOUT seconds.
        """
        current_time = time.time()
        time_since_update = current_time - self.last_updated
        return time_since_update <= self.CONNECTION_TIMEOUT

    def time_since_last_update(self) -> float:
        """
        Returns the time in seconds since the last update.
        """
        return time.time() - self.last_updated

    def update_power(self, production: int, consumption: int, script: 'Script' = None):
        """
        Updates the power production and consumption for the board.
        Only adds to history when the round changes.
        """
        # Determine current round from script
        current_round = -1
        if script:
            current_round = script.current_round_index
        
        # Check if round has changed and we have valid round data
        if current_round != self.current_round_index and current_round > 0:
            # Save the last values from the previous round to history
            if self.current_round_index >= 0:  # Only save if we had a previous round
                self.production_history.append(self.production)
                self.consumption_history.append(self.consumption)
                self.round_history.append(self.current_round_index)
                print(f"Board {self.id}: Saved round {self.current_round_index} to history - Production: {self.production}, Consumption: {self.consumption}", file=sys.stderr)
            
            # Update current round tracker
            self.current_round_index = current_round
        
        # Update current values
        self.production = production
        self.consumption = consumption
        self.last_updated = time.time()

    def finalize_current_round(self):
        """
        Manually finalize the current round by saving current values to history.
        Useful when game ends or when you want to ensure the last round is captured.
        """
        if self.current_round_index >= 0:
            self.production_history.append(self.production)
            self.consumption_history.append(self.consumption)
            self.round_history.append(self.current_round_index)
            print(f"Board {self.id}: Finalized round {self.current_round_index} - Production: {self.production}, Consumption: {self.consumption}", file=sys.stderr)

    def get_history_for_round(self, round_index: int) -> Optional[tuple]:
        """
        Get the production and consumption values for a specific round.
        Returns tuple (production, consumption) or None if round not found.
        """
        try:
            history_index = self.round_history.index(round_index)
            return (self.production_history[history_index], self.consumption_history[history_index])
        except (ValueError, IndexError):
            return None

    def get_round_indices(self) -> List[int]:
        """
        Get all round indices that have been recorded in history.
        """
        return self.round_history.copy()

    def has_unsaved_current_round(self) -> bool:
        """
        Check if the current round has data that hasn't been saved to history yet.
        Useful to know if finalize_current_round() should be called.
        """
        return (self.current_round_index >= 0 and 
                (not self.round_history or self.round_history[-1] != self.current_round_index))

    def replace_connected_consumption(self, consumption: List[int]):
        """
        Replaces the connected consumption list.
        """
        self.connected_consumption = consumption

    def replace_connected_production(self, production: List[int]):
        """
        Replaces the connected production list.
        """
        self.connected_production = production

    def get_connected_consumption(self) -> List[int]:
        """
        Returns the connected consumption list.
        """
        return self.connected_consumption

    def get_connected_production(self) -> List[int]:
        """
        Returns the connected production list.
        """
        return self.connected_production

    def update_power_generation_by_type(self, power_type: str, generation: float):
        """
        Updates the power generation for a specific power plant type.
        """
        self.power_generation_by_type[power_type] = generation
        self.last_updated = time.time()

    def get_power_generation_by_type(self, power_type: str) -> float:
        """
        Returns the power generation for a specific power plant type.
        """
        return self.power_generation_by_type.get(power_type, 0.0)

    def get_all_power_generation_by_type(self) -> Dict[str, float]:
        """
        Returns all power generation data by type.
        """
        return self.power_generation_by_type.copy()

    def set_power_generation_data(self, generation_data: Dict[str, float]):
        """
        Sets multiple power generation values at once.
        """
        self.power_generation_by_type.update(generation_data)
        self.last_updated = time.time()

    def add_connected_building(self, uid: str, building_type: int):
        """
        Add a connected building to the board state.
        """
        # Remove if already exists
        self.connected_buildings = [b for b in self.connected_buildings if b['uid'] != uid]
        self.connected_buildings.append({'uid': uid, 'building_type': building_type})
        self.last_updated = time.time()

    def remove_connected_building(self, uid: str):
        """
        Remove a connected building from the board state.
        """
        self.connected_buildings = [b for b in self.connected_buildings if b['uid'] != uid]
        self.last_updated = time.time()

    def get_connected_buildings(self) -> List[Dict[str, Any]]:
        """
        Get the list of connected buildings.
        """
        return self.connected_buildings.copy()

    def clear_connected_buildings(self):
        """
        Clear all connected buildings (e.g., when game ends).
        """
        self.connected_buildings = []
        self.last_updated = time.time()

    def to_dict(self):
        """
        Returns a dictionary representation of the board state.
        """
        return {
            "board_id": self.id,
            "display_name": self.display_name,
            "production": self.production,
            "consumption": self.consumption,
            "last_updated": self.last_updated,
            "connected": self.is_connected(),
            "time_since_update": self.time_since_last_update(),
            "connected_consumption": self.connected_consumption,
            "connected_production": self.connected_production,
            "production_history": self.production_history,
            "consumption_history": self.consumption_history,
            "round_history": self.round_history,
            "current_round_index": self.current_round_index,
            "power_generation_by_type": self.power_generation_by_type,
            "connected_buildings": self.connected_buildings,
        }