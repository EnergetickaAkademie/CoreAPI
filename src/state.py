from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import time
import sys
import os

from enak import Enak, Script

from scenarios.demo import getScript


available_scripts: Dict[str, Script] = {
    "demo": getScript()
}

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


class BoardState:
    """
    Represents the state of a board in the application.
    """
    def __init__(self, id: str):
        self.id = id
        self.production: int = 0
        self.consumption: int = 0
        self.last_updated: float = time.time()
        self.connected_consumption: List[int] = []
        self.connected_production: List[int] = []
        # History tracking for statistics
        self.production_history: List[int] = []
        self.consumption_history: List[int] = []

    def update_power(self, production: int, consumption: int):
        """
        Updates the power production and consumption for the board.
        """
        self.production = production
        self.consumption = consumption
        self.last_updated = time.time()
        
        # Add to history
        self.production_history.append(production)
        self.consumption_history.append(consumption)

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
