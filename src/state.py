from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import time

class RoundType(Enum):
    DAY = "day"
    NIGHT = "night"
    RAINY = "rainy"
    FOGGY = "foggy"
    LECTURE = "lecture"

# Power plant types
class PowerPlantType(Enum):
    FVE = 1           # Solar panels
    WIND = 2          # Wind turbine
    GAS = 3           # Gas turbine
    COAL = 4          # Coal power plant
    NUCLEAR = 5       # Nuclear power plant
    DAM = 6           # Hydroelectric dam

# Consumer types
class ConsumerType(Enum):
    CITY_CORE = 1     # City core
    BAKERY = 2        # Bakery
    HOUSING = 3       # Housing units
    MUSEUM = 4        # Museum
    STADIUM = 5       # Stadium
    TRAIN_STATION = 6 # Train station

@dataclass
class ScenarioRound:
    type: str
    page: Optional[int] = None
    coeff_prod_fve: Optional[float] = None
    
@dataclass
class Scenario:
    id: int
    name: str
    lecture_pdf: str
    round_types: List[str]
    weather_types: List[str]
    rounds: List[ScenarioRound]
    coefficients: Dict[str, Dict[str, float]]
    
    @classmethod
    def create_default_scenarios(cls) -> List['Scenario']:
        """Create default scenarios for the system"""
        return [
            cls(
                id=1,
                name="Basic Day/Night Cycle",
                lecture_pdf="https://example.com/basic-energy.pdf",
                round_types=["day", "night"],
                weather_types=["clear"],
                rounds=[
                    ScenarioRound(type="lecture", page=1),
                    ScenarioRound(type="day"),
                    ScenarioRound(type="night"),
                    ScenarioRound(type="lecture", page=2),
                ],
                coefficients={
                    "day": {"coeff_prod_fve": 1.0},
                    "night": {"coeff_prod_fve": 0.0},
                }
            ),
            cls(
                id=2,
                name="Weather Impact Simulation",
                lecture_pdf="https://example.com/weather-energy.pdf",
                round_types=["day", "night"],
                weather_types=["rainy", "foggy"],
                rounds=[
                    ScenarioRound(type="lecture", page=1),
                    ScenarioRound(type="rainy", coeff_prod_fve=0.5),
                    ScenarioRound(type="night"),
                    ScenarioRound(type="lecture", page=3),
                    ScenarioRound(type="foggy"),
                ],
                coefficients={
                    "day": {"coeff_prod_fve": 1.0},
                    "night": {"coeff_prod_fve": 0.0},
                    "rainy": {"coeff_prod_fve": 0.2, "coeff_consm": 1.5},
                    "foggy": {"coeff_prod_fve": 0.3, "coeff_consm": 1.2},
                }
            )
        ]

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
        
        # Username to board ID mapping
        self.username_to_board_id: Dict[str, int] = {}
        
        # Power plant default ranges (id -> (min_power, max_power))
        self.power_plant_ranges: Dict[int, tuple] = {
            PowerPlantType.FVE.value: (0, 100),        # Solar: 0-100W
            PowerPlantType.WIND.value: (0, 80),        # Wind: 0-80W
            PowerPlantType.GAS.value: (20, 150),       # Gas: 20-150W
            PowerPlantType.COAL.value: (50, 200),      # Coal: 50-200W
            PowerPlantType.NUCLEAR.value: (100, 300),  # Nuclear: 100-300W
            PowerPlantType.DAM.value: (30, 120),       # Dam: 30-120W
        }
        
        # Consumer default consumption values (id -> consumption_watts)
        self.consumer_consumption: Dict[int, int] = {
            ConsumerType.CITY_CORE.value: 150,      # City core: 150W
            ConsumerType.BAKERY.value: 45,          # Bakery: 45W
            ConsumerType.HOUSING.value: 80,         # Housing: 80W
            ConsumerType.MUSEUM.value: 25,          # Museum: 25W
            ConsumerType.STADIUM.value: 200,        # Stadium: 200W
            ConsumerType.TRAIN_STATION.value: 120,  # Train station: 120W
        }
        
        # Available scenarios
        self.scenarios = {s.id: s for s in Scenario.create_default_scenarios()}
        self.current_scenario: Optional[Scenario] = None
        self.current_scenario_round = 0
        
        # Building consumption table: maps building type (uint8) to consumption (int32)
        # Consumption is stored in centi-watts (watts * 100) for binary protocol compatibility
        self.building_consumption_table: Dict[int, int] = {
            1: 2500,   # Residential: 25.0W
            2: 5000,   # Commercial: 50.0W
            3: 7500,   # Industrial: 75.0W
            4: 1500,   # Educational: 15.0W
            5: 3000,   # Hospital: 30.0W
            6: 1000,   # Public: 10.0W
            7: 4000,   # Data Center: 40.0W
            8: 2000,   # Agricultural: 20.0W
        }
        self.building_table_version = int(time.time())  # Unix timestamp as version
    
    def update_building_consumption_table(self, table: Dict[int, int]) -> bool:
        """Update the building consumption table and increment version"""
        try:
            # Validate table entries
            for building_type, consumption in table.items():
                if not (0 <= building_type <= 255):  # uint8 range
                    return False
                if not (-2147483648 <= consumption <= 2147483647):  # int32 range
                    return False
            
            self.building_consumption_table = table.copy()
            self.building_table_version = int(time.time())
            return True
        except Exception:
            return False
    
    def get_building_consumption_table(self) -> Dict[int, int]:
        """Get a copy of the building consumption table"""
        return self.building_consumption_table.copy()
    
    def get_building_table_version(self) -> int:
        """Get the current table version"""
        return self.building_table_version
    
    def get_building_table(self) -> Dict[int, int]:
        """Get a copy of the building consumption table (alias for get_building_consumption_table)"""
        return self.get_building_consumption_table()
    
    def update_building_table(self, table: Dict[int, int]) -> int:
        """Update the building consumption table and return new version"""
        if self.update_building_consumption_table(table):
            return self.building_table_version
        else:
            raise ValueError("Invalid building table data")
    
    def get_power_plant_ranges(self) -> Dict[int, tuple]:
        """Get power plant controllability ranges"""
        return self.power_plant_ranges.copy()
    
    def get_consumer_consumption(self) -> Dict[int, int]:
        """Get consumer consumption values"""
        return self.consumer_consumption.copy()
    
    def get_scenarios(self) -> List[Dict]:
        """Get list of available scenarios"""
        return [{"id": s.id, "name": s.name} for s in self.scenarios.values()]
    
    def start_game_with_scenario(self, scenario_id: int) -> bool:
        """Start game with specific scenario"""
        if scenario_id not in self.scenarios:
            return False
        
        self.current_scenario = self.scenarios[scenario_id]
        self.current_scenario_round = 0
        self.game_active = True
        self.current_round = 1
        self.total_rounds = len(self.current_scenario.rounds)
        
        for board in self.boards.values():
            board.reset_score()
        
        return True
    
    def get_current_pdf_url(self) -> Optional[str]:
        """Get PDF URL for current scenario"""
        if self.current_scenario:
            return self.current_scenario.lecture_pdf
        return None

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
        
        # Create username mapping based on board_id
        if board_id >= 4000:  # ESP32 simulation boards
            username_map = {4001: 'board1', 4002: 'board2', 4003: 'board3'}
            if board_id in username_map:
                self.username_to_board_id[username_map[board_id]] = board_id
        
        return self.boards[board_id]
    
    def get_board_id_from_username(self, username: str) -> Optional[int]:
        """Get board ID from username"""
        return self.username_to_board_id.get(username)
    
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
        
        # Connected power plants and consumers
        self.connected_power_plants: Dict[int, int] = {}  # plant_id -> set_power
        self.connected_consumers: List[int] = []  # list of consumer_ids
    
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
    
    def set_connected_power_plants(self, power_plants: Dict[int, int]):
        """Set connected power plants with their set power levels"""
        self.connected_power_plants = power_plants.copy()
    
    def set_connected_consumers(self, consumers: List[int]):
        """Set connected consumers"""
        self.connected_consumers = consumers.copy()
