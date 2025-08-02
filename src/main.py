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
from state import GameState, available_scripts, BoardState
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

# Helper function to get game state for current user
def get_user_game_state(user_info: dict) -> GameState:
    """Get the game state for the user's group"""
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
        
        board.update_power(production, consumption)
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
    
    # Load the selected script and reset completely
    script = available_scripts[scenario_id]
    # script.current_round_index = 0  # Reset script to beginning
    
    
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

@app.route('/get_pdf', methods=['GET'])
@require_lecturer_auth
def get_pdf():
    """Get PDF URL for current scenario"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    script = user_game_state.get_script()
    if script:
        pdf_filename = script.getPDF()
        if pdf_filename:
            return jsonify({
                "success": True,
                "url": f"/coreapi/download_pdf/{pdf_filename}"
            })
    
    return jsonify({
        "success": True,
        "url": "/coreapi/download_pdf/presentation.pdf"  # Default PDF
    })

@app.route('/download_pdf/<filename>', methods=['GET'])
@optional_auth  # Changed from require_lecturer_auth to allow iframe access
def download_pdf(filename):
    """Download PDF file from presentations directory"""
    import os
    
    # In Docker, presentations directory is at ./presentations/
    presentations_dir = os.path.join(os.path.dirname(__file__), 'presentations')
    try:
        return send_from_directory(presentations_dir, filename)
    except FileNotFoundError:
        return jsonify({"error": "PDF file not found"}), 404

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
            if hasattr(current_round_obj, 'startSlide') and hasattr(current_round_obj, 'endSlide'):
                response_data["slide_range"] = {
                    "start": current_round_obj.startSlide,
                    "end": current_round_obj.endSlide
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
        
        return jsonify(response_data)
    else:
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
        all_boards.append({
            "board_id": board_id,
            "production": board.production,
            "consumption": board.consumption,
            "connected_production": board.connected_production,
            "connected_consumption": board.connected_consumption,
            "last_updated": board.last_updated
        })
    
    # Parse user metadata
    user = getattr(request, 'user', {})
    
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
        }
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host="0.0.0.0", port=port)