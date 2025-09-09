from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pickle
import os
import json
import time
import sys
import struct
import logging
import traceback
import random
import numpy as np
from state import GameState, available_scripts, available_script_generators, get_fresh_script, BoardState
from simple_auth import require_lecturer_auth, require_board_auth, require_auth, optional_auth, auth
from binary_protocol import BoardBinaryProtocol, BinaryProtocolError
from enak import Enak, Source
from MeritOrder import Power
from scoring import calculate_final_scores

def convert_numpy_types(obj):
    """Convert NumPy types to native Python types for JSON serialization"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    return obj

app = Flask(__name__)

# Configure debug mode from environment
DEBUG_MODE = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes', 'on')

# Configure logging based on debug mode
if DEBUG_MODE:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
else:
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

logger = logging.getLogger(__name__)

# Log startup mode
if DEBUG_MODE:
    logger.info("Application started in DEBUG mode - verbose logging enabled")
else:
    logger.warning("Application started in PRODUCTION mode - minimal logging enabled")

# Enable CORS for all routes
CORS(app, origins=['http://localhost'], 
     allow_headers=['Content-Type', 'Authorization', 'X-Auth-Token'],
     supports_credentials=True)

# Group-based game state management
class GroupGameManager:
    def __init__(self):
        self.group_game_states = {}
    
    def get_game_state(self, group_id: str) -> GameState:
        """Get or create game state for a specific group"""
        if group_id not in self.group_game_states:
            # Initialize with NO script - game is inactive by default
            self.group_game_states[group_id] = GameState(None)
        return self.group_game_states[group_id]
    
    def get_all_groups(self) -> list:
        """Get list of all group IDs"""
        return list(self.group_game_states.keys())

# Initialize group game manager
group_manager = GroupGameManager()

def generate_game_statistics(game_state: GameState):
    """
    Generate comprehensive game statistics for end-of-game display.
    Returns detailed board statistics and real team performance data using the scoring system.
    """
    
    # Mapping from Source enum names to Power enum values for scoring
    SOURCE_TO_POWER_MAP = {
        'COAL': Power.COAL,
        'GAS': Power.GAS,
        'NUCLEAR': Power.NUCLEAR,
        'HYDRO': Power.WATER,
        'HYDRO_STORAGE': Power.WATER_STORAGE,
        'WIND': Power.WIND,
        'PHOTOVOLTAIC': Power.PHOTOVOLTAIC,
        'BATTERY': Power.BATTERY
    }
    
    statistics = {
        "boards": [],
        "team_performance": {},
        "game_summary": {
            "total_rounds": 0,
            "game_duration_minutes": 0,
            "scenario_name": "Unknown"
        }
    }
    
    script = game_state.get_script()
    if script:
        statistics["game_summary"]["total_rounds"] = len(script.rounds)
        statistics["game_summary"]["scenario_name"] = script.__class__.__name__
    
    # Build history data in the format expected by the scoring system
    # history = [round1_data, round2_data, ...]
    # where round_data = {"Team A": {'productions': [(Power.NUCLEAR, 1500), ...], 'total_consumption': 1600}, ...}
    
    # First, collect all rounds that were played by any board
    all_round_indices = set()
    for board in game_state.boards.values():
        all_round_indices.update(board.round_history)
    
    if not all_round_indices:
        logger.debug("No round history found for any boards")
        # Return empty statistics with boards data only
        for board_id, board in game_state.boards.items():
            board_stats = board.to_dict()
            board_stats["total_energy_produced"] = 0
            board_stats["total_energy_consumed"] = 0
            board_stats["average_production"] = 0
            board_stats["average_consumption"] = 0
            board_stats["energy_balance"] = 0
            board_stats["average_production_by_type"] = {}
            statistics["boards"].append(board_stats)
            
            # Add mock scores since we have no real data
            statistics["team_performance"][board_id] = {
                "team_name": board.display_name,
                "team_number": board_id.replace('board', '') if board_id.startswith('board') else board_id,
                "ecology": 50,
                "elmix": 50,
                "finances": 50,
                "popularity": 50
            }
        return statistics
    
    # Sort rounds chronologically
    sorted_rounds = sorted(all_round_indices)
    
    # Build history for scoring system
    history = []
    
    for round_index in sorted_rounds:
        round_data = {}
        
        for board_id, board in game_state.boards.items():
            team_name = board.display_name
            
            # Get data for this specific round from board history
            if round_index in board.round_history:
                history_idx = board.round_history.index(round_index)
                
                # Get consumption for this round
                if history_idx < len(board.consumption_history):
                    total_consumption = board.consumption_history[history_idx]
                else:
                    total_consumption = 0
                
                # Get power plant data for this round
                powerplant_data = board.get_powerplant_history_for_round(round_index)
                productions = []
                
                if powerplant_data and 'power_generation_by_type' in powerplant_data:
                    power_gen = powerplant_data['power_generation_by_type']
                    
                    for source_name, generation in power_gen.items():
                        if generation > 0:  # Only include active generation
                            # Map source name to Power enum
                            power_type = SOURCE_TO_POWER_MAP.get(source_name.upper())
                            if power_type:
                                # Ensure we pass clean Power enum value, not tuple
                                clean_power = power_type
                                if hasattr(power_type, 'value') and isinstance(power_type.value, tuple):
                                    # Handle case where enum value is a tuple
                                    clean_power = Power(power_type.value[0])
                                productions.append((clean_power, generation))
                
                # If no production data, try to infer from total production
                if not productions and history_idx < len(board.production_history):
                    # Only apply legacy fallback if board has never reported per-type data
                    has_any_type_data = bool(board.get_all_power_generation_by_type())
                    total_production = board.production_history[history_idx]
                    if total_production > 0 and not has_any_type_data:
                        # Legacy boards (pre prod_connected update) – attribute to GAS to keep scoring working
                        productions.append((Power.GAS, total_production))
                
                round_data[team_name] = {
                    'productions': productions,
                    'total_consumption': total_consumption
                }
            else:
                # Board didn't participate in this round
                round_data[team_name] = {
                    'productions': [],
                    'total_consumption': 0
                }
        
        history.append(round_data)
    
    # Calculate real scores using the scoring system
    try:
        logger.debug("Attempting to calculate scores with history format check...")
        # Debug: Print first entry format
        if history:
            logger.debug(f"First history entry sample: {list(history[0].items())[0] if history[0] else 'Empty'}")
            
        final_scores = calculate_final_scores(history)
        logger.debug(f"Calculated final scores: {final_scores}")
    except Exception as e:
        logger.error(f"Error calculating scores: {e}")
        logger.debug(f"History data: {history}")
        # Try to provide a more detailed error trace
        import traceback
        logger.debug(f"Full traceback: {traceback.format_exc()}")
        final_scores = {}
    
    # Process each board's complete data
    for board_id, board in game_state.boards.items():
        board_stats = board.to_dict()
        
        # Add calculated statistics
        board_stats["total_energy_produced"] = sum(board.production_history) if board.production_history else 0
        board_stats["total_energy_consumed"] = sum(board.consumption_history) if board.consumption_history else 0
        board_stats["average_production"] = (
            sum(board.production_history) / len(board.production_history) 
            if board.production_history else 0
        )
        board_stats["average_consumption"] = (
            sum(board.consumption_history) / len(board.consumption_history) 
            if board.consumption_history else 0
        )
        board_stats["energy_balance"] = board_stats["total_energy_produced"] - board_stats["total_energy_consumed"]
        
        # Calculate production by type across all rounds
        production_by_type_summary = {}
        for round_data in board.powerplant_history:
            for plant_type, production in round_data.get("power_generation_by_type", {}).items():
                if plant_type not in production_by_type_summary:
                    production_by_type_summary[plant_type] = []
                production_by_type_summary[plant_type].append(production)
        
        # Average production by type
        board_stats["average_production_by_type"] = {}
        for plant_type, productions in production_by_type_summary.items():
            board_stats["average_production_by_type"][plant_type] = (
                sum(productions) / len(productions) if productions else 0
            )
        
        statistics["boards"].append(board_stats)
        
        # Get real team performance data from scoring system
        team_name = board.display_name
        team_number = board_id.replace('board', '') if board_id.startswith('board') else board_id
        
        if team_name in final_scores:
            scores = final_scores[team_name]
            statistics["team_performance"][board_id] = {
                "team_name": team_name,
                "team_number": team_number,
                "ecology": convert_numpy_types(scores.get("eco", 0)),
                "elmix": convert_numpy_types(scores.get("emx", 0)),
                "finances": convert_numpy_types(scores.get("fin", 0)),
                "popularity": convert_numpy_types(scores.get("pop", 0))
            }
        else:
            # Fallback to basic calculated scores if scoring system fails
            total_production = sum(board.production_history) if board.production_history else 0
            total_consumption = sum(board.consumption_history) if board.consumption_history else 0
            energy_balance = total_production - total_consumption
            
            # Simple scoring based on energy balance (basic fallback)
            balance_score = max(0, min(100, 100 - abs(energy_balance) / max(total_consumption, 1) * 10))
            
            logger.debug(f"No scores found for team {team_name}, using calculated fallback")
            statistics["team_performance"][board_id] = {
                "team_name": team_name,
                "team_number": team_number,
                "ecology": balance_score,
                "elmix": balance_score,
                "finances": balance_score,
                "popularity": balance_score
            }
    
    # Log statistics to console for debugging
    if DEBUG_MODE:
        logger.debug("=== GAME STATISTICS ===")
        logger.debug(f"Scenario: {statistics['game_summary']['scenario_name']}")
        logger.debug(f"Total Rounds: {statistics['game_summary']['total_rounds']}")
        logger.debug(f"Teams: {len(statistics['boards'])}")
        logger.debug(f"History rounds processed: {len(history)}")
        
        for board_stats in statistics["boards"]:
            board_id = board_stats["board_id"]
            logger.debug(f"\n{board_stats['display_name']} ({board_id}):")
            logger.debug(f"  Total Production: {board_stats['total_energy_produced']} MW")
            logger.debug(f"  Total Consumption: {board_stats['total_energy_consumed']} MW")
            logger.debug(f"  Energy Balance: {board_stats['energy_balance']} MW")
            logger.debug(f"  Rounds Played: {len(board_stats['round_history'])}")
            logger.debug(f"  Connected Buildings: {len(board_stats['connected_buildings'])}")
            
            team_perf = statistics["team_performance"].get(board_id, {})
            logger.debug(f"  Performance - Ecology: {team_perf.get('ecology', 0)}%, "
                        f"ElMix: {team_perf.get('elmix', 0)}%, "
                        f"Finances: {team_perf.get('finances', 0)}%, "
                        f"Popularity: {team_perf.get('popularity', 0)}%")
        
        logger.debug("=== END GAME STATISTICS ===")
    
    return statistics

# Display text translations for the dashboard
DISPLAY_TRANSLATIONS = {
    # Weather conditions
    'SUNNY': {
        'name': 'jasno',
        'temperature': '25°',
        'icon_url': '/icons/DASH_sunny.svg',
        'background_image': 'url(/icons/bg_sunny.jpg)',
        'wind_speed': '3 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Solární elektrárny vyrábí na plný výkon',
                'icon_url': '/icons/DASH_solarPP.svg',
                'type': Source.PHOTOVOLTAIC.value,
                'priority' : 0
            }
        ]
    },
    'PARTLY_CLOUDY': {
        'name': 'polojasno',
        'temperature': '20°',
        'icon_url': '/icons/DASH_cloud.svg',
        'background_image': 'url(/icons/bg_partly_cloudy.jpg)',
        'wind_speed': '4 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Solární elektrárny vyrábí na poloviční výkon',
                'icon_url': '/icons/DASH_solarPP.svg',
                'type' :  Source.PHOTOVOLTAIC.value,
                'priority' : 1
            }
        ]
    },
    'CLOUDY': {
        'name': 'oblačno',
        'temperature': '15°',
        'icon_url': '/icons/DASH_cloud.svg',
        'background_image': 'url(/icons/bg_cloudy.jpg)',
        'wind_speed': '2 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Solární elektrárny nevyrábí',
                'icon_url': '/icons/DASH_solarPP.svg',
                'type' :  Source.PHOTOVOLTAIC.value,
                'priority' : 2
            }
        ]
    },
    'WINDY': {
        'name': 'větrno',
        'temperature': '18°',
        'icon_url': '/icons/DASH_wind-velocity.svg',
        'background_image': 'url(/icons/bg_windy.jpg)',
        'wind_speed': '8 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Větrné elektrárny vyrábí na plný výkon',
                'icon_url': '/icons/DASH_windPP.svg',
                'type' :  Source.WIND.value,
                'priority' : 0
            }
        ]
    },
    'BREEZY': {
        'name': 'mírný vítr',
        'temperature': '16°',
        'icon_url': '/icons/DASH_wind-velocity.svg',
        'background_image': 'url(/icons/bg_breezy.jpg)',
        'wind_speed': '5 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Větrné elektrárny vyrábí na poloviční výkon',
                'icon_url': '/icons/DASH_windPP.svg',
                'type' :  Source.WIND.value,
                'priority' : 1
            }
        ]
    },
    'CALM': {
        'name': 'bezvětří',
        'temperature': '22°',
        'icon_url': '/icons/DASH_sunny.svg',
        'background_image': 'url(/icons/bg_calm.jpg)',
        'wind_speed': '0 m/s',
        'show_wind': False,
        'effects': [
            {
                'text': 'Větrné elektrárny nevyrábí',
                'icon_url': '/icons/DASH_windPP.svg',
                'type' :  Source.WIND.value,
                'priority' : 2
            }
        ]
    },
    'RAINY': {
        'name': 'deštivo',
        'temperature': '12°',
        'icon_url': '/icons/DASH_cloud.svg',
        'background_image': 'url(/icons/bg_rainy.jpg)',
        'wind_speed': '6 m/s',
        'show_wind': True,
        'effects': []
    },
    'SNOWY': {
        'name': 'sněžení',
        'temperature': '-2°',
        'icon_url': '/icons/DASH_cloud.svg',
        'background_image': 'url(/icons/bg_snowy.jpg)',
        'wind_speed': '4 m/s',
        'show_wind': True,
        'effects': [
            {
                'text': 'Solární elektrárny nevyrábí',
                'icon_url': '/icons/DASH_solarPP.svg',
                'type' :  Source.PHOTOVOLTAIC.value,
                'priority' : 2
            }
        ]
    },
    'FOGGY': {
        'name': 'mlhavo',
        'temperature': '8°',
        'icon_url': '/icons/DASH_cloud.svg',
        'background_image': 'url(/icons/bg_foggy.jpg)',
        'wind_speed': '1 m/s',
        'show_wind': True,
        'effects': []
    },
    # Round types (fallback when no specific weather)
    'DAY': {
        'name': 'Den',
        'temperature': '25°',
        'weather_type': 'skoro jasno',
        'icon_url': '/icons/DASH_sunny.svg',
        'background_image': 'url(/icons/bg_day.jpg)',
        'wind_speed': '5 m/s',
        'show_wind': True,
        'effects': []
    },
    'NIGHT': {
        'name': 'Noc',
        'temperature': '10°',
        'weather_type': 'jasná noc',
        'icon_url': '/icons/DASH_moon.svg',
        'background_image': 'url(/icons/bg_night.jpg)',
        'wind_speed': '2 m/s',
        'show_wind': False,
        'effects': [
            {
                'text': 'Solární elektrárny nevyrábí',
                'icon_url': '/icons/DASH_solarPP.svg',
                'type' :  Source.PHOTOVOLTAIC.value,
                'priority' : 2
            },
        ]
    }
}

# Helper function to get game state for current user
def get_user_game_state(user_info: dict) -> GameState:
    """Get the game state for the user's group"""
    if user_info is None:
        # Default to group1 for unauthenticated requests
        group_id = 'group1'
    else:
        group_id = user_info.get('group_id', 'group1')
    return group_manager.get_game_state(group_id)

def filter_effects_by_priority(display_data):
    """
    Filter effects to show only the highest priority effect for each power plant type.
    Higher priority numbers have higher priority (2 is highest, 0 is lowest).
    Only filters effects that have both 'type' and 'priority' fields (power plant effects).
    """
    if 'effects' not in display_data or not display_data['effects']:
        return display_data
    
    # Separate power plant effects (have type and priority) from other effects
    power_plant_effects = []
    other_effects = []
    
    for effect in display_data['effects']:
        if effect.get('type') is not None and 'priority' in effect:
            power_plant_effects.append(effect)
        else:
            other_effects.append(effect)
    
    # Group power plant effects by type
    effects_by_type = {}
    for effect in power_plant_effects:
        effect_type = effect.get('type')
        if effect_type not in effects_by_type:
            effects_by_type[effect_type] = []
        effects_by_type[effect_type].append(effect)
    
    # Keep only the highest priority effect for each power plant type
    filtered_power_plant_effects = []
    for effect_type, effects in effects_by_type.items():
        # Sort by priority (higher number = higher priority)
        effects.sort(key=lambda x: x.get('priority', 0), reverse=True)
        # Take the first (highest priority) effect
        filtered_power_plant_effects.append(effects[0])
    
    # Combine filtered power plant effects with other effects (keep all other effects)
    all_filtered_effects = other_effects + filtered_power_plant_effects
    
    # Create a copy of display_data with filtered effects
    filtered_display_data = display_data.copy()
    filtered_display_data['effects'] = all_filtered_effects
    
    return filtered_display_data

# Game state (backwards compatibility - will use group1 by default)
game_state = group_manager.get_game_state('group1')

@app.route('/login', methods=['POST'])
def login():
    """Login endpoint for both lecturers and boards"""
    if DEBUG_MODE:
        logger.debug("Request data for login:")
        logger.debug(f"Request data: {request.data}")
        logger.debug("endpoint: /login")

    data = request.get_json()
    
    username = data.get('username')
    password = data.get('password')
    logger.info(f"Login attempt for user: {username}")
    if DEBUG_MODE:
        logger.debug(f"User password: {password}")  # Only log password in debug mode
    if not data:
        return jsonify({'error': 'JSON data required'}), 400
    
    if not username or not password:
        logger.error("Username or password not provided")
        return jsonify({'error': 'Username and password required'}), 400
    
    user_info = auth.authenticate_user(username, password)
    
    if not user_info:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    token = auth.generate_token(user_info)
    
    return jsonify({
        'token': token,
        'user_type': user_info['user_type'],
        'username': user_info['username'],
        'group_id': user_info.get('group_id', 'group1')
    })

@app.route('/poll_binary', methods=['GET'])
@require_board_auth
def poll_binary():
    """Optimized binary poll endpoint for ESP32"""
    try:
        # Get board ID from authentication (from JWT username)
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Extract board ID from username
        if username.startswith('board'):
            board_id = username[5:]  # Remove 'board' prefix
        else:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board = user_game_state.get_board(board_id)
        if not board:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        script = user_game_state.get_script()
        if not script or script.current_round_index >= len(script.rounds):
            # Return empty response when no game is active / game finished
            # This signals to ESP32 that game is paused/ended (gameActive = false)
            return b'', 200, {'Content-Type': 'application/octet-stream'}

        # Get production coefficients
        prod_coeffs = script.getCurrentProductionCoefficients()
        
        # Get consumption for all buildings
        cons_coeffs = {}
        for building in Enak.Building:
            consumption = script.getCurrentBuildingConsumption(building)
            if consumption is not None:
                cons_coeffs[building] = consumption

        # Get connected buildings for this board
        connected_buildings = board.get_connected_buildings()

        # Pack the data using the new method
        response = BoardBinaryProtocol.pack_coefficients_response(
            production_coeffs=prod_coeffs,
            consumption_coeffs=cons_coeffs,
            connected_buildings=connected_buildings
        )
        
        return response, 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        logger.error(f"Binary protocol error in poll_binary: {e}")
        return b'PROTOCOL_ERROR', 500, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        logger.error(f"Internal error in poll_binary: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'INTERNAL_ERROR', 500, {'Content-Type': 'application/octet-stream'}



@app.route('/prod_vals', methods=['GET'])
@require_board_auth
def get_production_values():
    """Binary endpoint - Get power plant production ranges"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        script = user_game_state.get_script()
        if not script:
            return b'SCRIPT_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        # Get production ranges from script (includes coefficients applied)
        from enak.Enak import Source
        prod_ranges = {}
        
        # Get all available sources and their current production ranges
        for source in Source:
            range_values = script.getCurrentProductionRange(source)
            if range_values and range_values != (0.0, 0.0):
                prod_ranges[source] = range_values
        if DEBUG_MODE:
            logger.debug(f"Production ranges: {prod_ranges}")
        
        # Pack using binary protocol
        data = BoardBinaryProtocol.pack_production_ranges(prod_ranges)
        return data, 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        logger.error(f"Error in get_production_values: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/cons_vals', methods=['GET'])
@require_board_auth
def get_consumption_values():
    """Binary endpoint - Get consumer consumption values"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        script = user_game_state.get_script()
        if not script:
            return b'SCRIPT_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        # Get consumption for all buildings from script
        cons_coeffs = {}
        for building in Enak.Building:
            consumption = script.getCurrentBuildingConsumption(building)
            if consumption is not None:
                cons_coeffs[building] = consumption
        
        # Pack using binary protocol
        data = BoardBinaryProtocol.pack_consumption_values(cons_coeffs)
        return data, 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        logger.error(f"Error in get_consumption_values: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/post_vals', methods=['POST'])
@require_board_auth
def post_values():
    """Binary endpoint - Board posts current production and consumption"""
    try:
        data = request.get_data()
        
        # All boards must send the new format with buildings data
        try:
            production, consumption, connected_buildings = BoardBinaryProtocol.unpack_power_data_with_buildings(data)
        except BinaryProtocolError as e:
            logger.error(f"Invalid power data format from board - new format required: {e}")
            return b'INVALID_FORMAT', 400, {'Content-Type': 'application/octet-stream'}
        
        print(f"Received production: {production}, consumption: {consumption}, buildings: {len(connected_buildings)}", file=sys.stderr)
        # Get board ID from authentication (from JWT username)
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Extract board ID from username (assuming username is like 'board1', 'board2', etc.)
        if username.startswith('board'):
            board_id = username[5:]  # Remove 'board' prefix
        else:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Get the board and update power
        board = user_game_state.get_board(board_id)
        if not board:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        # Always replace connected buildings list since all boards now send new format
        previous_count = len(board.get_connected_buildings()) if hasattr(board, 'get_connected_buildings') else 'n/a'
        board.clear_connected_buildings()
        if connected_buildings:
            for building in connected_buildings:
                try:
                    board.add_connected_building(building['uid'], building['building_type'])
                except Exception as e:
                    print(f"Failed to add building {building}: {e}", file=sys.stderr)
        # Debug trace to verify clearing behavior
        print(f"Board {board_id}: replaced connected_buildings (prev={previous_count}, new={len(connected_buildings)})", file=sys.stderr)
        
        # Pass the script to track round changes
        script = user_game_state.get_script()
        board.update_power(production, consumption, script)
        return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        logger.error(f"Binary protocol error in post_values: {e}")
        return b'PROTOCOL_ERROR', 400, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        logger.error(f"Error in post_values: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/prod_connected', methods=['POST'])
@require_board_auth
def post_production_connected():
    """Binary endpoint - Board reports connected power plants"""
    try:
        data = request.get_data()
        if len(data) < 1:
            return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
        
        # Unpack: count(1) + [id(4) + set_power(4)] * count
        count = struct.unpack('B', data[:1])[0]
        offset = 1
        
        # power_plants: plant_id -> set_power_mW (as sent from board)
        power_plants: dict[int,int] = {}
        for i in range(count):
            if offset + 8 > len(data):
                return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
            plant_id, set_power_mw = struct.unpack('>Ii', data[offset:offset+8])
            power_plants[plant_id] = set_power_mw
            offset += 8
        
        # Get board ID from authentication (from JWT username)
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Extract board ID from username
        if username.startswith('board'):
            board_id = username[5:]  # Remove 'board' prefix
        else:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Update board's connected power plants
        board = user_game_state.get_board(board_id)
        if board:
            # Store just the IDs for backwards compatibility / UI
            board.replace_connected_production(list(power_plants.keys()))

            # Map numeric IDs (from firmware) to source names expected by scoring.
            # These IDs MUST stay aligned with power_plant_config.h / Enak.Source.
            ID_TO_SOURCE = {
                1: 'PHOTOVOLTAIC',
                2: 'WIND',
                3: 'NUCLEAR',
                4: 'GAS',
                5: 'HYDRO',
                6: 'HYDRO_STORAGE',
                7: 'COAL',
                8: 'BATTERY'
            }

            # Update per‑type generation in Watts (board sends mW)
            reported_ids = set()
            for pid, mw in power_plants.items():
                if pid in ID_TO_SOURCE:
                    reported_ids.add(pid)
                    watts = mw / 1000.0
                    board.update_power_generation_by_type(ID_TO_SOURCE[pid], float(watts))
            # Zero out any previously present types that are no longer reported (disconnected)
            existing_types = list(board.get_all_power_generation_by_type().keys())
            for existing in existing_types:
                # Find its numeric id inverse map
                # If its id not in reported_ids this cycle, set to zero to avoid stale values
                try:
                    # Build inverse lookup lazily
                    # (cheap given tiny mapping)
                    inv = {v: k for k, v in ID_TO_SOURCE.items()}
                    if inv.get(existing) and inv[existing] not in reported_ids:
                        board.update_power_generation_by_type(existing, 0.0)
                except Exception:
                    pass

            return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        else:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        logger.error(f"Error in post_production_connected: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/cons_connected', methods=['POST'])
@require_board_auth
def post_consumption_connected():
    """Binary endpoint - Board reports connected consumers"""
    try:
        data = request.get_data()
        if len(data) < 1:
            return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
        
        # Unpack: count(1) + [id(4)] * count
        count = struct.unpack('B', data[:1])[0]
        offset = 1
        
        consumers = []
        for i in range(count):
            if offset + 4 > len(data):
                return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
            
            consumer_id = struct.unpack('>I', data[offset:offset+4])[0]
            consumers.append(consumer_id)
            offset += 4
        
        # Get board ID from authentication (from JWT username)
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Extract board ID from username
        if username.startswith('board'):
            board_id = username[5:]  # Remove 'board' prefix
        else:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Update board's connected consumers
        board = user_game_state.get_board(board_id)
        if board:
            board.replace_connected_consumption(consumers)
            return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        else:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        logger.error(f"Error in post_consumption_connected: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/register', methods=['POST'])
@require_board_auth
def register():
    """Binary board registration endpoint - board ID extracted from JWT only"""
    try:
        # Extract board ID from JWT token, not from request data
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Extract board ID from username (e.g., 'board1' -> '1')
        if username.startswith('board'):
            board_id = username[5:]  # Remove 'board' prefix
        else:
            logger.error(f"Invalid board username in register: {username}")
            response = BoardBinaryProtocol.pack_registration_response(False, "Invalid board authentication")
            return response, 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Register the board (no need to validate board_id since it comes from verified JWT)
        user_game_state.register_board(board_id)
        
        logger.info(f"Board {board_id} registered successfully")
        response = BoardBinaryProtocol.pack_registration_response(True, "Registration successful")
        return response, 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        logger.error(f"Internal error in register: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        response = BoardBinaryProtocol.pack_registration_response(False, "Internal error")
        return response, 500, {'Content-Type': 'application/octet-stream'}

# Frontend/Lecturer Endpoints

@app.route('/scenarios', methods=['GET'])
@require_lecturer_auth
def get_scenarios():
    """Get list of available scenarios"""
    scenarios = list(available_scripts.keys())
    return jsonify({
        "success": True,
        "scenarios": scenarios
    })

@app.route('/start_game', methods=['POST'])
@require_lecturer_auth
def start_game_scenario():
    """Start game with specific scenario"""
    data = request.get_json()
    scenario_id = data.get('scenario_id')
    
    if not scenario_id:
        return jsonify({"error": "scenario_id is required"}), 400
    
    if scenario_id not in available_scripts:
        return jsonify({"error": "Invalid scenario ID"}), 400
    
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    # Get a fresh script instance to ensure clean state
    try:
        script = get_fresh_script(scenario_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    
    # Reset existing per-board state (connected buildings, histories) so
    # a quick restart does not leak previous game data.
    try:
        user_game_state.reset_for_new_game()
    except Exception as e:
        print(f"Warning: failed to reset boards for new game: {e}", file=sys.stderr)

    # Set the script
    user_game_state.script = script
    
    # DON'T automatically advance - let frontend decide when to start
    
    user = getattr(request, 'user', {})
    lecturer_name = user.get('username', 'Unknown Lecturer')
    
    return jsonify({
        "status": "success", 
        "message": f"Game started with scenario {scenario_id}", 
        "started_by": lecturer_name,
        "scenario_id": scenario_id
    })

@app.route('/slide_file/<path:filename>', methods=['GET'])
@optional_auth  # Allow access for slide images
def get_slide_file(filename):
    """Get slide image by filename path"""
    import os
    
    # Get presentations directory
    presentations_dir = os.path.join(os.path.dirname(__file__), 'presentations')
    
    # Construct full path
    filepath = os.path.join(presentations_dir, filename)
    
    # Security check: ensure the path is within presentations directory
    real_presentations_dir = os.path.realpath(presentations_dir)
    real_filepath = os.path.realpath(filepath)
    
    if not real_filepath.startswith(real_presentations_dir):
        return jsonify({"error": "Invalid file path"}), 403
    
    # Check if file exists
    if os.path.exists(real_filepath):
        try:
            # Extract directory and filename
            file_dir = os.path.dirname(real_filepath)
            file_name = os.path.basename(real_filepath)
            return send_from_directory(file_dir, file_name)
        except FileNotFoundError:
            return jsonify({"error": f"File {filename} not found"}), 404
    
    return jsonify({"error": f"File {filename} not found"}), 404

@app.route('/next_round', methods=['POST'])
@require_lecturer_auth 
def next_round():
    """Advance to next round"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    if not script:
        return jsonify({"error": "No active game script"}), 400
    
    user = getattr(request, 'user', {})
    lecturer_name = user.get('username', 'Unknown Lecturer')
    
    # Save current round data to history for all boards BEFORE advancing
    user_game_state.save_all_boards_current_round_to_history()
    
    # Do one step in the script
    if script.step():
        current_round = script.current_round_index
        round_type = script.getCurrentRoundType()
        
        response_data = {
            "status": "success", 
            "round": current_round, 
            "advanced_by": lecturer_name,
            "round_type": round_type.value if round_type else None
        }
        
        # Add type-specific information
        if round_type and round_type == Enak.RoundType.SLIDE:
            current_round_obj = script.getCurrentRound()
            if hasattr(current_round_obj, 'getSlide'):
                response_data["slide"] = current_round_obj.getSlide()
        elif round_type and round_type == Enak.RoundType.SLIDE_RANGE:
            slides = script.getCurrentSlides()
            if slides:
                # Send the raw slide paths to frontend - no conversion needed
                response_data["slides"] = slides
                
                # Also extract slide numbers for backwards compatibility with slide_range field
                slide_numbers = []
                for slide_path in slides:
                    # Extract slide number from path (e.g., "1" from "slides/1.png")
                    try:
                        slide_num = int(slide_path.split('/')[-1].split('.')[0])
                        slide_numbers.append(slide_num)
                    except (ValueError, IndexError):
                        # If we can't parse the number, try to extract it differently
                        import re
                        match = re.search(r'(\d+)', slide_path)
                        if match:
                            slide_numbers.append(int(match.group(1)))
                
                if slide_numbers:
                    slide_numbers.sort()
                    response_data["slide_range"] = {
                        "start": min(slide_numbers),
                        "end": max(slide_numbers)
                    }
        elif round_type and round_type in [Enak.RoundType.DAY, Enak.RoundType.NIGHT]:
            # Get current production coefficients and building consumptions
            prod_coeffs = script.getCurrentProductionCoefficients()
            cons_modifiers = {}
            
            # Get building consumptions
            for building in Enak.Building:
                consumption = script.getCurrentBuildingConsumption(building)
                if consumption is not None:
                    cons_modifiers[building.name] = consumption
            
            response_data["game_data"] = {
                "production_coefficients": {str(k): v for k, v in prod_coeffs.items()},
                "consumption_modifiers": cons_modifiers
            }
            
            # Add display data for weather/round information
            round_key = round_type.name  # 'DAY' or 'NIGHT'
            
            # Check if there's specific weather data in the script
            current_round_obj = script.getCurrentRound()
            weather_key = None
            
            # Try to get weather from the round object
            if hasattr(current_round_obj, 'weather') and current_round_obj.weather:
                if isinstance(current_round_obj.weather, list) and len(current_round_obj.weather) > 0:
                    weather_key = current_round_obj.weather[0].name.upper()
                elif hasattr(current_round_obj.weather, 'upper'):
                    weather_key = current_round_obj.weather.upper()
            elif hasattr(current_round_obj, 'getWeather') and current_round_obj.getWeather():
                weather_data = current_round_obj.getWeather()
                if isinstance(weather_data, list) and len(weather_data) > 0:
                    weather_key = weather_data[0].name.upper()
                elif hasattr(weather_data, 'upper'):
                    weather_key = weather_data.upper()
            
            # Use specific weather data if available, otherwise fall back to generic round data
            if weather_key and weather_key in DISPLAY_TRANSLATIONS:
                display_data = DISPLAY_TRANSLATIONS[weather_key].copy()
            else:
                display_data = DISPLAY_TRANSLATIONS[round_key].copy()
            
            # Filter effects to show only highest priority for each power plant type
            display_data = filter_effects_by_priority(display_data)
            
            response_data["display_data"] = display_data
        
        return jsonify(response_data)
    else:
        # Game is finished, finalize current round for all boards
        user_game_state.finalize_all_boards_current_round()
        # prune stale / disconnected boards to free memory
        user_game_state.prune_disconnected_boards()
        
        # Generate game statistics for display
        game_statistics = generate_game_statistics(user_game_state)
        
        return jsonify({
            "status": "game_finished", 
            "message": "All rounds completed", 
            "finished_by": lecturer_name,
            "game_statistics": game_statistics
        })

@app.route('/get_statistics', methods=['GET'])
@require_lecturer_auth
def get_statistics():
    """Get consumption and production statistics for all boards"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    
    statistics = []
    
    for board_id, board in user_game_state.boards.items():
        stats = {
            "board_id": board_id,
            "display_name": board.display_name,
            "current_production": board.production,
            "current_consumption": board.consumption,
            "connected": board.is_connected(),
            "time_since_update": board.time_since_last_update(),
            "production_history": board.production_history,
            "consumption_history": board.consumption_history,
            "round_history": board.round_history,
            "powerplant_history": board.powerplant_history,
            "current_power_generation_by_type": board.power_generation_by_type,
            "connected_production": board.connected_production,
            "connected_consumption": board.connected_consumption,
            "last_updated": board.last_updated
        }
        statistics.append(stats)
    
    # Get connection summary
    connection_summary = user_game_state.get_connection_summary()
    
    return jsonify({
        "success": True,
        "statistics": statistics,
        "connection_summary": connection_summary,
        "game_status": {
            "current_round": script.current_round_index if script else 0,
            "total_rounds": len(script.rounds) if script else 0,
            "game_active": script is not None and script.current_round_index < len(script.rounds),
            "scenario": script.__class__.__name__ if script else None
        }
    })

@app.route('/game_statistics', methods=['GET'])
@require_lecturer_auth
def get_game_statistics():
    """Get comprehensive game statistics using the scoring system - for end-of-game display"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    
    # Check if game is finished
    if script and script.current_round_index < len(script.rounds):
        return jsonify({
            "error": "Game is still active. Statistics are only available after game completion."
        }), 400
    
    # Generate comprehensive game statistics
    game_statistics = generate_game_statistics(user_game_state)
    
    # Convert any NumPy types to JSON-serializable types
    game_statistics = convert_numpy_types(game_statistics)
    
    return jsonify({
        "success": True,
        "game_statistics": game_statistics,
        "game_status": {
            "current_round": script.current_round_index if script else 0,
            "total_rounds": len(script.rounds) if script else 0,
            "game_active": script is not None and script.current_round_index < len(script.rounds),
            "scenario": script.__class__.__name__ if script else None
        }
    })

@app.route('/powerplant_history', methods=['GET'])
@require_lecturer_auth
def get_powerplant_history():
    """Get detailed power plant history for all boards"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    
    powerplant_data = {}
    
    for board_id, board in user_game_state.boards.items():
        board_powerplant_history = []
        
        # Get all power plant history for this board
        for round_data in board.powerplant_history:
            round_info = {
                "round_index": round_data["round_index"],
                "round_type": round_data["round_type"],
                "connected_production": round_data["connected_production"],
                "power_generation_by_type": round_data["power_generation_by_type"],
                "total_production": round_data["total_production"],
                "timestamp": round_data["timestamp"]
            }
            board_powerplant_history.append(round_info)
        
        powerplant_data[board_id] = {
            "board_id": board_id,
            "display_name": board.display_name,
            "powerplant_history": board_powerplant_history,
            "current_power_generation": board.power_generation_by_type
        }
    
    return jsonify({
        "success": True,
        "powerplant_data": powerplant_data,
        "game_status": {
            "current_round": script.current_round_index if script else 0,
            "total_rounds": len(script.rounds) if script else 0,
            "game_active": script is not None and script.current_round_index < len(script.rounds),
            "scenario": script.__class__.__name__ if script else None
        }
    })

@app.route('/end_game', methods=['POST'])
@require_lecturer_auth
def end_game():
    """End the current game"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    # Finalize current round for all boards before ending the game
    user_game_state.finalize_all_boards_current_round()
    # Remove any boards that are no longer connected (timeout passed)
    user_game_state.prune_disconnected_boards()
    # Clear transient per-game data (esp. connected buildings) so a future
    # start without process restart is clean.
    try:
        user_game_state.reset_for_new_game()
    except Exception as e:
        print(f"Warning: failed to reset boards on end_game: {e}", file=sys.stderr)
    # Reset script to null/none (no active game)
    user_game_state.script = None
    
    user = getattr(request, 'user', {})
    lecturer_name = user.get('username', 'Unknown Lecturer')
    
    return jsonify({
        "status": "success",
        "message": "Game ended",
        "ended_by": lecturer_name
    })

@app.route('/pollforusers', methods=['GET'])
@require_lecturer_auth
def poll_for_users():
    """Endpoint for authenticated lecturers to get status of all boards"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    script = user_game_state.get_script()
    
    all_boards = []
    
    for board_id, board in user_game_state.boards.items():
        all_boards.append(board.to_dict())
    
    # Parse user metadata
    user = getattr(request, 'user', {})
    
    # Get connection summary
    connection_summary = user_game_state.get_connection_summary()
    
    # Build detailed round information
    round_details = {}
    if script and script.current_round_index > 0:
        current_round = script.getCurrentRound()
        round_type = script.getCurrentRoundType()
        
        if current_round and round_type:
            round_details = {
                "round_type": round_type.value,
                "round_type_name": str(round_type),
                "comment": current_round.getComment() if hasattr(current_round, 'getComment') else None,
                "info_file": current_round.getInfoFile() if hasattr(current_round, 'getInfoFile') else None
            }
            
            # Add weather information for PlayRounds
            if round_type in [Enak.RoundType.DAY, Enak.RoundType.NIGHT]:
                weather = script.getCurrentWeather()
                if weather:
                    round_details["weather"] = [
                        {
                            "type": w.value,
                            "name": str(w)
                        } for w in weather
                    ]
                else:
                    round_details["weather"] = []
                
                # Add production coefficients for current round
                prod_coeffs = script.getCurrentProductionCoefficients()
                if prod_coeffs:
                    round_details["production_coefficients"] = {
                        str(source): coefficient for source, coefficient in prod_coeffs.items()
                    }
                
                # Add building consumptions/modifiers for current round
                building_modifiers = {}
                for building in Enak.Building:
                    consumption = script.getCurrentBuildingConsumption(building)
                    if consumption is not None:
                        building_modifiers[building.name] = consumption
                
                if building_modifiers:
                    round_details["building_consumptions"] = building_modifiers
            
            # Add slide information for Slide rounds
            elif round_type == Enak.RoundType.SLIDE:
                if hasattr(current_round, 'getSlide'):
                    round_details["slide"] = current_round.getSlide()
            
            # Add slides information for SlideRange rounds  
            elif round_type == Enak.RoundType.SLIDE_RANGE:
                if hasattr(current_round, 'getSlides'):
                    round_details["slides"] = current_round.getSlides()
    
    return jsonify({
        "boards": all_boards,
        "connection_summary": connection_summary,
        "game_status": {
            "current_round": script.current_round_index if script else 0,
            "total_rounds": len(script.rounds) if script else 0,
            "round_type": script.getCurrentRoundType().value if script and script.getCurrentRoundType() else None,
            "game_active": script is not None and script.current_round_index < len(script.rounds) if script else False
        },
        "lecturer_info": {
            "user_id": user.get('user_id'),
            "username": user.get('username', 'Unknown')
        },
        "round_details": round_details
    })

@app.route('/game/status', methods=['GET'])
@optional_auth
def game_status():
    # Get user's game state  
    user_game_state = get_user_game_state(getattr(request, 'user', {'group_id': 'group1'}))
    script = user_game_state.get_script()
    
    base_status = {
        "current_round": script.current_round_index if script else 0,
        "total_rounds": len(script.rounds) if script else 0,
        "round_type": script.getCurrentRoundType().value if script and script.getCurrentRoundType() else None,
        "game_active": script is not None and script.current_round_index < len(script.rounds) if script else False,
        "boards": len(user_game_state.boards)
    }
    
    # Add detailed information for authenticated users
    user = getattr(request, 'user', None)
    if user:
        user_type = user.get('user_type')
        if user_type == 'lecturer':
            pass
        elif user_type == 'board':
            pass
    
    return jsonify(base_status)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Docker and load balancers"""
    # Use default game state for health check
    default_game_state = group_manager.get_game_state('group1')
    script = default_game_state.get_script()
    
    return jsonify({
        "status": "healthy",
        "service": "CoreAPI",
        "boards_registered": len(default_game_state.boards),
        "game_active": script is not None and script.current_round_index < len(script.rounds) if script else False,
        "current_round": script.current_round_index if script else None
    })

@app.route('/building_table', methods=['GET'])
@require_lecturer_auth
def get_building_table():
    """Get the building power consumption table from script"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    if not script:
        return jsonify({'error': 'No active script'}), 400
    
    # Get building consumptions from script
    table = {}
    for building in Enak.Building:
        consumption = script.getCurrentBuildingConsumption(building)
        if consumption is not None:
            table[building.value] = consumption
    
    return jsonify({
        'success': True,
        'table': table,
        'version': 1  # Static version since it comes from script
    })

@app.route('/dashboard', methods=['GET'])
@require_auth
def dashboard():
    """Get user profile information for the dashboard"""
    user_info = request.user
    
    return jsonify({
        'success': True,
        'user': {
            'id': user_info['user_id'],  # JWT payload uses 'user_id' not 'id'
            'username': user_info['username'],
            'user_type': user_info['user_type'],
            'group_id': user_info.get('group_id', 'group1')
        }
    })

@app.route('/translations', methods=['GET'])
def get_translations():
    """Get translation dictionaries for the dashboard"""
    
    # Apply priority filtering to weather translations
    filtered_weather = {}
    for k, v in DISPLAY_TRANSLATIONS.items():
        if k not in ['DAY', 'NIGHT']:
            filtered_weather[k] = filter_effects_by_priority(v.copy())
    
    # Apply priority filtering to round type translations  
    filtered_round_types = {}
    for k, v in DISPLAY_TRANSLATIONS.items():
        if k in ['DAY', 'NIGHT']:
            filtered_round_types[k] = filter_effects_by_priority(v.copy())
    
    return jsonify({
        'success': True,
        'weather': filtered_weather,
        'round_types': filtered_round_types
    })

# Lecturer Interface Endpoints (Lecturer Authentication Required)

@app.route('/lecturer/simulation_dump', methods=['GET'])
@require_lecturer_auth
def lecturer_simulation_dump():
    """
    Get complete simulation data dump for all groups and boards.
    Available to lecturers without authentication for external tools.
    """
    try:
        simulation_data = {
            "timestamp": time.time(),
            "groups": {},
            "summary": {
                "total_groups": 0,
                "total_boards": 0,
                "active_games": 0
            }
        }
        
        # Iterate through all groups
        for group_id in group_manager.get_all_groups():
            group_game_state = group_manager.get_game_state(group_id)
            script = group_game_state.get_script()
            
            group_data = {
                "group_id": group_id,
                "game_status": {
                    "active": script is not None,
                    "current_round": script.current_round_index if script else 0,
                    "total_rounds": len(script.rounds) if script else 0,
                    "round_type": script.getCurrentRoundType().value if script and script.getCurrentRoundType() else None,
                    "scenario": script.__class__.__name__ if script else None,
                    "game_finished": script is not None and script.current_round_index >= len(script.rounds) if script else False
                },
                "boards": {},
                "production_coefficients": {},
                "consumption_modifiers": {},
                "powerplant_ranges": {}
            }
            
            # Add game data if script is active
            if script:
                try:
                    # Get current production coefficients
                    prod_coeffs = script.getCurrentProductionCoefficients()
                    group_data["production_coefficients"] = {str(k): v for k, v in prod_coeffs.items()}
                    
                    # Get building consumptions
                    for building in Enak.Building:
                        consumption = script.getCurrentBuildingConsumption(building)
                        if consumption is not None:
                            group_data["consumption_modifiers"][building.name] = consumption
                    
                    # Get powerplant ranges (same as prod_vals endpoint)
                    prod_ranges = {}
                    for source in Enak.Source:
                        range_values = script.getCurrentProductionRange(source)
                        if range_values and range_values != (0.0, 0.0):
                            prod_ranges[source.name] = {
                                "min": range_values[0],
                                "max": range_values[1]
                            }
                    group_data["powerplant_ranges"] = prod_ranges
                            
                    if script.current_round_index < len(script.rounds):
                        simulation_data["summary"]["active_games"] += 1
                except Exception as e:
                    logger.error(f"Error getting script data for group {group_id}: {e}")
            
            # Add board data
            for board_id, board in group_game_state.boards.items():
                board_data = board.to_dict()
                # Add some additional computed fields for the dump
                board_data["production_history"] = board.production_history[-10:]  # Last 10 entries
                board_data["consumption_history"] = board.consumption_history[-10:]  # Last 10 entries
                board_data["history_length"] = {
                    "production": len(board.production_history),
                    "consumption": len(board.consumption_history)
                }
                
                group_data["boards"][board_id] = board_data
                simulation_data["summary"]["total_boards"] += 1
            
            # Add connection summary for the group
            group_data["connection_summary"] = group_game_state.get_connection_summary()
            
            simulation_data["groups"][group_id] = group_data
            simulation_data["summary"]["total_groups"] += 1
        
        return jsonify(simulation_data)
        
    except Exception as e:
        logger.error(f"Error in lecturer_simulation_dump: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "error": "Failed to generate simulation dump",
            "message": str(e),
            "timestamp": time.time()
        }), 500

@app.route('/lecturer/submit_board_data', methods=['POST'])
@require_lecturer_auth
def lecturer_submit_board_data():
    """
    Submit data for a specific board as a lecturer (board spoofing for debugging).
    Requires lecturer authentication but allows submitting data for any board.
    
    Expected JSON payload:
    {
        "group_id": "group1",  // optional, defaults to lecturer's group
        "board_id": "1",
        "production": 100,
        "consumption": 80,
        "connected_production": [10, 20, 30],  // optional
        "connected_consumption": [15, 25],     // optional
        "power_generation_by_type": {          // optional
            "COAL": 150,
            "NUCLEAR": 950,
            "GAS": 450
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'JSON data required'}), 400
        
        # Extract required fields
        lecturer_user = getattr(request, 'user', {})
        lecturer_group_id = lecturer_user.get('group_id', 'group1')
        
        group_id = data.get('group_id', lecturer_group_id)  # Use lecturer's group if not specified
        board_id = data.get('board_id')
        production = data.get('production')
        consumption = data.get('consumption')
        
        if board_id is None:
            return jsonify({'error': 'board_id is required'}), 400
        
        if production is None or consumption is None:
            return jsonify({'error': 'production and consumption are required'}), 400
        
        # Validate data types
        try:
            production = int(production)
            consumption = int(consumption)
        except (ValueError, TypeError):
            return jsonify({'error': 'production and consumption must be integers'}), 400
        
        # Get the game state for the group
        group_game_state = group_manager.get_game_state(group_id)
        
        # Get or create the board
        if board_id not in group_game_state.boards:
            group_game_state.register_board(board_id)
        
        board = group_game_state.get_board(board_id)
        
        # Update basic power data with script for round tracking
        script = group_game_state.get_script()
        board.update_power(production, consumption, script)
        
        # Update connected arrays if provided
        connected_production = data.get('connected_production')
        connected_consumption = data.get('connected_consumption')
        
        if connected_production is not None:
            if isinstance(connected_production, list):
                try:
                    connected_production = [int(x) for x in connected_production]
                    board.replace_connected_production(connected_production)
                except (ValueError, TypeError):
                    return jsonify({'error': 'connected_production must be a list of integers'}), 400
            else:
                return jsonify({'error': 'connected_production must be a list'}), 400
        
        if connected_consumption is not None:
            if isinstance(connected_consumption, list):
                try:
                    connected_consumption = [int(x) for x in connected_consumption]
                    board.replace_connected_consumption(connected_consumption)
                except (ValueError, TypeError):
                    return jsonify({'error': 'connected_consumption must be a list of integers'}), 400
            else:
                return jsonify({'error': 'connected_consumption must be a list'}), 400
        
        # Update power generation by type if provided
        power_generation_by_type = data.get('power_generation_by_type')
        if power_generation_by_type is not None:
            if isinstance(power_generation_by_type, dict):
                try:
                    # Convert all values to float and validate
                    validated_power_gen = {}
                    for power_type, generation in power_generation_by_type.items():
                        validated_power_gen[str(power_type).upper()] = float(generation)
                    
                    board.set_power_generation_data(validated_power_gen)
                except (ValueError, TypeError) as e:
                    return jsonify({'error': f'power_generation_by_type values must be numbers: {str(e)}'}), 400
            else:
                return jsonify({'error': 'power_generation_by_type must be a dictionary'}), 400
        
        logger.info(f"Lecturer {lecturer_user.get('username', 'Unknown')} spoofed data for group {group_id}, board {board_id}: production={production}, consumption={consumption}")
        
        response_data = {
            'group_id': group_id,
            'board_id': board_id,
            'production': production,
            'consumption': consumption,
            'timestamp': board.last_updated
        }
        
        # Include power generation data in response if it was updated
        if power_generation_by_type is not None:
            response_data['power_generation_by_type'] = board.get_all_power_generation_by_type()
        
        return jsonify({
            'success': True,
            'message': f'Data spoofed for board {board_id} in group {group_id}',
            'spoofed_by': lecturer_user.get('username', 'Unknown'),
            'data': response_data
        })
        
    except Exception as e:
        logger.error(f"Error in lecturer_submit_board_data: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'error': 'Failed to submit board data',
            'message': str(e)
        }), 500

@app.route('/lecturer/board_status/<group_id>/<board_id>', methods=['GET'])
@require_lecturer_auth
def lecturer_board_status(group_id, board_id):
    """
    Get status of a specific board with lecturer authentication.
    Available to lecturers for monitoring and debugging.
    """
    try:
        # Get the game state for the group
        group_game_state = group_manager.get_game_state(group_id)
        
        # Check if board exists
        if board_id not in group_game_state.boards:
            return jsonify({
                'error': 'Board not found',
                'group_id': group_id,
                'board_id': board_id
            }), 404
        
        board = group_game_state.get_board(board_id)
        script = group_game_state.get_script()
        
        return jsonify({
            'success': True,
            'group_id': group_id,
            'board_id': board_id,
            'board_data': {
                'production': board.production,
                'consumption': board.consumption,
                'last_updated': board.last_updated,
                'connected_production': board.connected_production,
                'connected_consumption': board.connected_consumption,
                'production_history': board.production_history[-5:],  # Last 5 entries
                'consumption_history': board.consumption_history[-5:]   # Last 5 entries
            },
            'game_status': {
                'active': script is not None,
                'current_round': script.current_round_index if script else 0,
                'total_rounds': len(script.rounds) if script else 0,
                'round_type': script.getCurrentRoundType().value if script and script.getCurrentRoundType() else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error in lecturer_board_status: {e}")
        return jsonify({
            'error': 'Failed to get board status',
            'message': str(e)
        }), 500

@app.route('/lecturer/simulate_board_poll/<group_id>/<board_id>', methods=['GET'])
@require_lecturer_auth
def lecturer_simulate_board_poll(group_id, board_id):
    """
    Simulate the board polling process for debugging.
    Returns the same data that a board would receive from /poll_binary but in JSON format.
    """
    try:
        # Get the game state for the group
        group_game_state = group_manager.get_game_state(group_id)
        
        # Check if board exists, create if not
        if board_id not in group_game_state.boards:
            group_game_state.register_board(board_id)
        
        board = group_game_state.get_board(board_id)
        script = group_game_state.get_script()
        
        if not script:
            return jsonify({
                'success': True,
                'group_id': group_id,
                'board_id': board_id,
                'message': 'No active game script',
                'game_data': {
                    'production_coefficients': {},
                    'consumption_coefficients': {}
                }
            })

        # Get production coefficients (same as binary endpoint)
        prod_coeffs = script.getCurrentProductionCoefficients()
        
        # Get consumption for all buildings
        cons_coeffs = {}
        for building in Enak.Building:
            consumption = script.getCurrentBuildingConsumption(building)
            if consumption is not None:
                cons_coeffs[building.name] = consumption

        lecturer_user = getattr(request, 'user', {})
        
        return jsonify({
            'success': True,
            'group_id': group_id,
            'board_id': board_id,
            'simulated_by': lecturer_user.get('username', 'Unknown'),
            'game_data': {
                'production_coefficients': {str(k): v for k, v in prod_coeffs.items()},
                'consumption_coefficients': cons_coeffs
            },
            'game_status': {
                'active': True,
                'current_round': script.current_round_index,
                'total_rounds': len(script.rounds),
                'round_type': script.getCurrentRoundType().value if script.getCurrentRoundType() else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error in lecturer_simulate_board_poll: {e}")
        return jsonify({
            'error': 'Failed to simulate board poll',
            'message': str(e)
        }), 500

@app.route('/lecturer/simulate_board_register/<group_id>/<board_id>', methods=['POST'])
@require_lecturer_auth
def lecturer_simulate_board_register(group_id, board_id):
    """
    Simulate board registration for debugging.
    Registers a board as if it connected via the binary protocol.
    """
    try:
        # Get the game state for the group
        group_game_state = group_manager.get_game_state(group_id)
        
        # Register the board
        group_game_state.register_board(board_id)
        
        lecturer_user = getattr(request, 'user', {})
        logger.info(f"Lecturer {lecturer_user.get('username', 'Unknown')} simulated registration for group {group_id}, board {board_id}")
        
        return jsonify({
            'success': True,
            'message': f'Board {board_id} registered successfully in group {group_id}',
            'simulated_by': lecturer_user.get('username', 'Unknown'),
            'group_id': group_id,
            'board_id': board_id
        })
        
    except Exception as e:
        logger.error(f"Error in lecturer_simulate_board_register: {e}")
        return jsonify({
            'error': 'Failed to simulate board registration',
            'message': str(e)
        }), 500

# Power Generation by Type Endpoints

@app.route('/power_generation/<board_id>', methods=['GET'])
@require_board_auth
def get_power_generation_by_type(board_id):
    """Get power generation data by type for a specific board"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board = user_game_state.get_board(board_id)
        if not board:
            return jsonify({'error': 'Board not found'}), 404
        
        return jsonify({
            'success': True,
            'board_id': board_id,
            'power_generation_by_type': board.get_all_power_generation_by_type()
        })
        
    except Exception as e:
        logger.error(f"Error in get_power_generation_by_type: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/power_generation/<board_id>', methods=['POST'])
@require_board_auth  
def update_power_generation_by_type(board_id):
    """Update power generation data by type for a specific board"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON data required'}), 400
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board = user_game_state.get_board(board_id)
        if not board:
            return jsonify({'error': 'Board not found'}), 404
        
        # Update power generation data
        generation_data = data.get('power_generation_by_type', {})
        if generation_data:
            board.set_power_generation_data(generation_data)
        
        return jsonify({
            'success': True,
            'board_id': board_id,
            'updated_data': board.get_all_power_generation_by_type()
        })
        
    except Exception as e:
        logger.error(f"Error in update_power_generation_by_type: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/power_generation/<board_id>/<power_type>', methods=['POST'])
@require_board_auth
def update_single_power_generation(board_id, power_type):
    """Update power generation for a specific power plant type"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON data required'}), 400
        
        generation = data.get('generation')
        if generation is None:
            return jsonify({'error': 'Generation value required'}), 400
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board = user_game_state.get_board(board_id)
        if not board:
            return jsonify({'error': 'Board not found'}), 404
        
        # Update single power generation value
        board.update_power_generation_by_type(power_type.upper(), float(generation))
        
        return jsonify({
            'success': True,
            'board_id': board_id,
            'power_type': power_type.upper(),
            'generation': board.get_power_generation_by_type(power_type.upper())
        })
        
    except Exception as e:
        logger.error(f"Error in update_single_power_generation: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Lecturer endpoint to view all power generation data
@app.route('/lecturer/power_generation', methods=['GET'])
@require_lecturer_auth
def lecturer_get_all_power_generation():
    """Get power generation data for all boards (lecturer view)"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        all_power_data = {}
        for board_id, board in user_game_state.boards.items():
            all_power_data[board_id] = {
                'board_id': board_id,
                'power_generation_by_type': board.get_all_power_generation_by_type(),
                'total_production': board.production,
                'last_updated': board.last_updated
            }
        
        return jsonify({
            'success': True,
            'power_generation_data': all_power_data
        })
        
    except Exception as e:
        logger.error(f"Error in lecturer_get_all_power_generation: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Configuration Management Endpoints
@app.route('/connection_status', methods=['GET'])
@require_lecturer_auth
def get_connection_status():
    """Get detailed connection status for all boards"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        connection_summary = user_game_state.get_connection_summary()
        
        # Add detailed board information
        detailed_boards = []
        for board_id, board in user_game_state.boards.items():
            board_info = {
                'board_id': board_id,
                'connected': board.is_connected(),
                'time_since_update': board.time_since_last_update(),
                'last_updated': board.last_updated,
                'current_production': board.production,
                'current_consumption': board.consumption,
                'connection_timeout': BoardState.CONNECTION_TIMEOUT
            }
            detailed_boards.append(board_info)
        
        return jsonify({
            'success': True,
            'connection_summary': connection_summary,
            'detailed_boards': detailed_boards,
            'connection_timeout_seconds': BoardState.CONNECTION_TIMEOUT
        })
        
    except Exception as e:
        logger.error(f"Error in get_connection_status: {e}")
        return jsonify({'error': f'Error getting connection status: {str(e)}'}), 500

@app.route('/config/reload', methods=['POST'])
@require_lecturer_auth
def reload_configuration():
    """Reload configuration from TOML file"""
    try:
        # Reload configuration
        success = auth.reload_configuration()
        if success:
            return jsonify({'message': 'Configuration reloaded successfully'})
        else:
            return jsonify({'error': 'Failed to reload configuration'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Error reloading configuration: {str(e)}'}), 500

@app.route('/config/users', methods=['GET'])
@require_lecturer_auth
def get_configured_users():
    """Get list of all configured users (without passwords)"""
    try:
        from user_config import get_user_config
        config = get_user_config()
        
        board_users = config.get_boards()
        lecturer_users = config.get_lecturers()
        
        # Remove passwords from response
        for user in board_users + lecturer_users:
            user.pop('password', None)
        
        return jsonify({
            'boards': board_users,
            'lecturers': lecturer_users,
            'total_boards': len(board_users),
            'total_lecturers': len(lecturer_users)
        })
        
    except ImportError:
        return jsonify({'error': 'User configuration not available'}), 500
    except Exception as e:
        return jsonify({'error': f'Error getting users: {str(e)}'}), 500

@app.route('/config/groups', methods=['GET'])
@require_lecturer_auth
def get_configured_groups():
    """Get list of all configured groups"""
    try:
        from user_config import get_user_config
        config = get_user_config()
        
        groups = config.get_groups()
        
        return jsonify({'groups': groups})
        
    except ImportError:
        return jsonify({'error': 'User configuration not available'}), 500
    except Exception as e:
        return jsonify({'error': f'Error getting groups: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)