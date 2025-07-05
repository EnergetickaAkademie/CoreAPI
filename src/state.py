from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

class RoundType(Enum):
    DAY = "day"
    NIGHT = "night"

@dataclass
class RoundConfig:
    type: RoundType
    description: str
    reward_matrix: Dict[str, int]

class GameState:
    def __init__(self):
        self.total_rounds = 10
        self.current_round = 0
        self.round_types = [RoundType.DAY, RoundType.NIGHT] * 5  # Alternating day/night
        self.round_configs = {
            RoundType.DAY: RoundConfig(
                type=RoundType.DAY,
                description="Day round - solar generation expected",
                reward_matrix={
                    "perfect": 10,    # within 5% match
                    "over": 4,        # over production
                    "under_5": 1,     # 5% under production
                    "under_10": 0     # 10% under production
                }
            ),
            RoundType.NIGHT: RoundConfig(
                type=RoundType.NIGHT,
                description="Night round - minimal generation expected",
                reward_matrix={
                    "perfect": 10,    # within 5% match
                    "over": 4,        # over production
                    "under_5": 0,     # 5% under production (penalty for night)
                    "under_10": 0     # 10% under production
                }
            )
        }
        self.boards: Dict[int, Board] = {}
        self.game_active = False
    
    def start_game(self):
        self.game_active = True
        self.current_round = 1
        for board in self.boards.values():
            board.reset_score()
    
    def next_round(self):
        if self.current_round < self.total_rounds:
            self.current_round += 1
            return True
        else:
            self.game_active = False
            return False
    
    def get_current_round_type(self) -> RoundType:
        if self.current_round == 0:
            return RoundType.DAY
        return self.round_types[self.current_round - 1]
    
    def register_board(self, board_id: int, board_name: str = None, board_type: str = "generic"):
        if board_name is None:
            board_name = f"Board {board_id}"
        
        self.boards[board_id] = Board(board_id, board_name, board_type)
        return self.boards[board_id]
    
    def update_board_power(self, board_id: int, generation: float = None, consumption: float = None, timestamp = None):
        if board_id not in self.boards:
            return False
        
        board = self.boards[board_id]
        if generation is not None:
            board.current_generation = generation
        if consumption is not None:
            board.current_consumption = consumption
        if timestamp is not None:
            # Handle both Unix timestamps (int) and ISO string timestamps (str)
            if isinstance(timestamp, int):
                # Unix timestamp - convert to string for compatibility
                import datetime
                board.last_update = datetime.datetime.fromtimestamp(timestamp).isoformat()
            else:
                # String timestamp (legacy)
                board.last_update = timestamp
        
        # Mark that this board has submitted data for the current round
        if self.game_active and self.current_round > 0:
            board.mark_data_submitted(self.current_round)
        
        return True
    
    def calculate_board_score(self, board_id: int) -> int:
        if board_id not in self.boards:
            return 0
        
        board = self.boards[board_id]
        generation = board.current_generation or 0
        consumption = board.current_consumption or 0
        
        if consumption == 0:
            return 0
        
        ratio = generation / consumption
        current_round_type = self.get_current_round_type()
        rewards = self.round_configs[current_round_type].reward_matrix
        
        if 0.95 <= ratio <= 1.05:  # within 5%
            return rewards["perfect"]
        elif ratio > 1.05:  # over production
            return rewards["over"]
        elif ratio >= 0.9:  # 5-10% under
            return rewards["under_5"]
        else:  # more than 10% under
            return rewards["under_10"]
    
    def get_board_status(self, board_id: int) -> Optional[Dict]:
        if board_id not in self.boards:
            return None
        
        board = self.boards[board_id]
        current_score = self.calculate_board_score(board_id)
        
        # Determine if we're expecting new data for this round
        # If the board hasn't submitted data for the current round yet, we expect it
        expecting_data = (self.game_active and 
                         board.last_data_round < self.current_round and
                         self.current_round > 0)
        
        return {
            "r": self.current_round,  # minimal field names for ESP32
            "s": board.total_score + current_score,
            "g": board.current_generation,
            "c": board.current_consumption,
            "rt": self.get_current_round_type().value,
            "expecting_data": expecting_data,  # New flag for boards
            "game_active": self.game_active
        }

class Board:
    def __init__(self, board_id: int, name: str, board_type: str):
        self.board_id = board_id
        self.name = name
        self.board_type = board_type
        self.current_generation: Optional[float] = None
        self.current_consumption: Optional[float] = None
        self.last_update: Optional[str] = None
        self.total_score = 0
        self.round_scores: List[int] = []
        self.last_data_round = 0  # Track which round data was last submitted for
    
    def reset_score(self):
        self.total_score = 0
        self.round_scores = []
        self.last_data_round = 0
    
    def add_round_score(self, score: int):
        self.round_scores.append(score)
        self.total_score += score
    
    def mark_data_submitted(self, round_number: int):
        """Mark that data has been submitted for this round"""
        self.last_data_round = round_number
