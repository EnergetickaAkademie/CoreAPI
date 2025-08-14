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
from state import GameState, available_scripts, available_script_generators, get_fresh_script, BoardState
from simple_auth import require_lecturer_auth, require_board_auth, require_auth, optional_auth, auth
from binary_protocol import BoardBinaryProtocol, BinaryProtocolError
from enak import Enak

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Translation dictionaries for the dashboard
WEATHER_TRANSLATIONS = {
    'SUNNY': {
        'name': 'jasno',
        'temperature': '25°',
        'effects': [
            {
                'text': 'Solární elektrárny vyrábí na plný výkon',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.591 1.59a.75.75 0 101.06 1.061l1.591-1.59zM21.75 12a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5H21a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 10-1.061 1.06l1.59 1.591zM12 18a.75.75 0 01.75.75V21a.75.75 0 01-1.5 0v-2.25A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.591 1.59a.75.75 0 001.06 1.061l1.591-1.59zM6 12a.75.75 0 01-.75.75H3a.75.75 0 010-1.5h2.25A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 00-1.061 1.06l1.59 1.591z"/></svg>'
            }
        ]
    },
    'PARTLY_CLOUDY': {
        'name': 'polojasno',
        'temperature': '20°',
        'effects': [
            {
                'text': 'Solární elektrárny vyrábí na poloviční výkon',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M4.5 9.75a6 6 0 0111.573-2.226 3.75 3.75 0 014.133 4.303A4.5 4.5 0 0118 20.25H6.75a5.25 5.25 0 01-2.23-10.004 6.072 6.072 0 01-.02-.496z"/></svg>'
            }
        ]
    },
    'CLOUDY': {
        'name': 'oblačno',
        'temperature': '15°',
        'effects': [
            {
                'text': 'Solární elektrárny nevyrábí',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M4.5 9.75a6 6 0 0111.573-2.226 3.75 3.75 0 014.133 4.303A4.5 4.5 0 0118 20.25H6.75a5.25 5.25 0 01-2.23-10.004 6.072 6.072 0 01-.02-.496z"/></svg>'
            }
        ]
    },
    'WINDY': {
        'name': 'větrno',
        'temperature': '18°',
        'effects': [
            {
                'text': 'Větrné elektrárny vyrábí na plný výkon',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3 8h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h11a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2z"/></svg>'
            }
        ]
    },
    'BREEZY': {
        'name': 'mírný vítr',
        'temperature': '16°',
        'effects': [
            {
                'text': 'Větrné elektrárny vyrábí na poloviční výkon',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3 8h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h11a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2z"/></svg>'
            }
        ]
    },
    'CALM': {
        'name': 'bezvětří',
        'temperature': '22°',
        'effects': [
            {
                'text': 'Větrné elektrárny nevyrábí',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>'
            }
        ]
    },
    'RAINY': {
        'name': 'deštivo',
        'temperature': '12°',
        'effects': []
    },
    'SNOWY': {
        'name': 'sněžení',
        'temperature': '-2°',
        'effects': [
            {
                'text': 'Solární elektrárny nevyrábí',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>'
            },
            {
                'text': 'Větrné elektrárny vyrábí na sníženém výkonu',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3 8h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h11a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2zm0 4h7a3 3 0 000-6 1 1 0 010-2 5 5 0 010 10H3a1 1 0 010-2z"/></svg>'
            },
            {
                'text': 'Baterie vyrábí na sníženém výkonu',
                'icon': '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.75 8.25v4.5a1.5 1.5 0 01-1.5 1.5h-6a1.5 1.5 0 01-1.5-1.5v-4.5a1.5 1.5 0 011.5-1.5h6a1.5 1.5 0 011.5 1.5zm1.5-1.5v7.5a3 3 0 01-3 3h-6a3 3 0 01-3-3v-7.5a3 3 0 013-3h6a3 3 0 013 3z"/></svg>'
            }
        ]
    },
    'FOGGY': {
        'name': 'mlhavo',
        'temperature': '8°',
        'effects': []
    }
}

ROUND_TYPE_TRANSLATIONS = {
    'DAY': {
        'name': 'Den',
        'icon': '<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.591 1.59a.75.75 0 101.06 1.061l1.591-1.59zM21.75 12a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5H21a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 10-1.061 1.06l1.59 1.591zM12 18a.75.75 0 01.75.75V21a.75.75 0 01-1.5 0v-2.25A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.591 1.59a.75.75 0 001.06 1.061l1.591-1.59zM6 12a.75.75 0 01-.75.75H3a.75.75 0 010-1.5h2.25A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 00-1.061 1.06l1.59 1.591z"/></svg>'
    },
    'NIGHT': {
        'name': 'Noc',
        'icon': '<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z"/></svg>'
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

# Game state (backwards compatibility - will use group1 by default)
game_state = group_manager.get_game_state('group1')

@app.route('/login', methods=['POST'])
def login():
    """Login endpoint for both lecturers and boards"""
    print("Request data for login:", file=sys.stderr)
    # extract raw string data
    print(f"Request data: {request.data}", file=sys.stderr)
    print("endpoint: /login", file=sys.stderr)

    data = request.get_json()
    
    username = data.get('username')
    password = data.get('password')
    logger.info(f"Login attempt for user: {username}")
    logger.info(f"User password: {password}")  # For debugging purposes, remove in production
    print(f"User password: {password}", file=sys.stderr)  # For debugging purposes, remove in production   
    print(f"Login attempt for user: {username}", file=sys.stderr)
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
        if not script:
            # Return empty response when no game is active
            response = BoardBinaryProtocol.pack_coefficients_response(
                production_coeffs={},
                consumption_coeffs={}
            )
            return response, 200, {'Content-Type': 'application/octet-stream'}

        # Get production coefficients
        prod_coeffs = script.getCurrentProductionCoefficients()
        
        # Get consumption for all buildings
        cons_coeffs = {}
        for building in Enak.Building:
            consumption = script.getCurrentBuildingConsumption(building)
            if consumption is not None:
                cons_coeffs[building] = consumption

        # Pack the data using the new method
        response = BoardBinaryProtocol.pack_coefficients_response(
            production_coeffs=prod_coeffs,
            consumption_coeffs=cons_coeffs
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
        print(f"Production ranges: {prod_ranges}", file=sys.stderr)
        
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
        
        # Unpack using binary protocol
        production, consumption = BoardBinaryProtocol.unpack_power_values(data)
        print(f"Received production: {production}, consumption: {consumption}", file=sys.stderr)
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
        
        power_plants = {}
        for i in range(count):
            if offset + 8 > len(data):
                return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
            
            plant_id, set_power = struct.unpack('>Ii', data[offset:offset+8])
            power_plants[plant_id] = set_power
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
            board.replace_connected_production([plant_id for plant_id in power_plants.keys()])
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
    
    # Do one step in the script
    if script.step():
        # Since we advanced to a new round, finalize previous round data for all boards
        # (The boards will handle this automatically in update_power, but this ensures 
        # that boards that haven't sent data yet will still have their previous round finalized)
        
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
                # Convert slide numbers to range format for frontend compatibility
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
                    response_data["slides"] = slide_numbers
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
        
        return jsonify(response_data)
    else:
        # Game is finished, finalize current round for all boards
        user_game_state.finalize_all_boards_current_round()
        return jsonify({
            "status": "game_finished", 
            "message": "All rounds completed", 
            "finished_by": lecturer_name
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
            "current_production": board.production,
            "current_consumption": board.consumption,
            "production_history": board.production_history,
            "consumption_history": board.consumption_history,
            "connected_production": board.connected_production,
            "connected_consumption": board.connected_consumption,
            "last_updated": board.last_updated
        }
        statistics.append(stats)
    
    return jsonify({
        "success": True,
        "statistics": statistics,
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
    
    # Reset script to null/none
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
    return jsonify({
        'success': True,
        'weather': WEATHER_TRANSLATIONS,
        'round_types': ROUND_TYPE_TRANSLATIONS
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)