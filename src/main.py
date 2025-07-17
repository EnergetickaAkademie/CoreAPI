from flask import Flask, request, jsonify
from flask_cors import CORS
import pickle
import os
import json
import time
import struct
from state import GameState
from simple_auth import require_lecturer_auth, require_board_auth, require_auth, optional_auth, auth
from binary_protocol import BoardBinaryProtocol, BinaryProtocolError
from config_loader import ConfigLoader

app = Flask(__name__)

# Enable CORS for all routes
CORS(app, origins=['http://localhost'], 
     allow_headers=['Content-Type', 'Authorization', 'X-Auth-Token'],
     supports_credentials=True)

# Initialize config loader (auth will use this automatically)
config_loader = ConfigLoader()

# Group-based game state management
class GroupGameManager:
    def __init__(self):
        self.group_game_states = {}
    
    def get_game_state(self, group_id: str) -> GameState:
        """Get or create game state for a specific group"""
        if group_id not in self.group_game_states:
            self.group_game_states[group_id] = GameState()
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
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'JSON data required'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    user_info = auth.authenticate_user(username, password)
    
    if not user_info:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    token = auth.generate_token(user_info)
    
    # Parse metadata if it's a JSON string
    metadata = {}
    if user_info['metadata']:
        try:
            metadata = json.loads(user_info['metadata'])
        except:
            metadata = {}
    
    return jsonify({
        'token': token,
        'user_type': user_info['user_type'],
        'username': user_info['username'],
        'name': user_info['name'],
        'metadata': metadata
    })

@app.route('/register_binary', methods=['POST'])
@require_board_auth
def register_binary():
    """Binary board registration endpoint optimized for ESP32"""
    try:
        data = request.get_data()
        board_id, board_name, board_type = BoardBinaryProtocol.unpack_registration_request(data)
        
        # Validate board_id
        if board_id <= 0:
            response = BoardBinaryProtocol.pack_registration_response(False, "Invalid board ID")
            return response, 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Register the board
        board = user_game_state.register_board(board_id, board_name, board_type)
        
        response = BoardBinaryProtocol.pack_registration_response(True, "Registration successful")
        return response, 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        response = BoardBinaryProtocol.pack_registration_response(False, str(e))
        return response, 400, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        response = BoardBinaryProtocol.pack_registration_response(False, "Internal error")
        return response, 500, {'Content-Type': 'application/octet-stream'}

@app.route('/power_data_binary', methods=['POST'])
@require_board_auth
def power_data_binary():
    """Binary power data submission endpoint optimized for ESP32"""
    try:
        data = request.get_data()
        board_id, generation, consumption, timestamp = BoardBinaryProtocol.unpack_power_data(data)
        
        # Validate timestamp (within reasonable bounds)
        current_time = int(time.time())
        if abs(timestamp - current_time) > 86400:  # More than 1 day difference
            return b'TIME_ERROR', 400, {'Content-Type': 'application/octet-stream'}
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        # Update board power
        if not user_game_state.update_board_power(board_id, generation=generation, 
                                           consumption=consumption, timestamp=timestamp):
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        return b'PROTOCOL_ERROR', 400, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        return b'INTERNAL_ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/power_generation', methods=['POST'])
@require_board_auth
def power_generation():
    """Legacy JSON power generation endpoint (deprecated, use /power_data_binary)"""
    data = request.get_json()
    board_id = data.get('board_id')
    power = data.get('power')
    timestamp = data.get('timestamp')
    
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    if not user_game_state.update_board_power(board_id, generation=power, timestamp=timestamp):
        return jsonify({"error": "Board not registered"}), 404
    
    return jsonify({
        "status": "success",
        "updated_by": getattr(request, 'user', {}).get('name', 'Unknown')
    })

@app.route('/power_consumption', methods=['POST'])
@require_board_auth
def power_consumption():
    """Legacy JSON power consumption endpoint (deprecated, use /power_data_binary)"""
    data = request.get_json()
    board_id = data.get('board_id')
    power = data.get('power')
    timestamp = data.get('timestamp')
    
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    if not user_game_state.update_board_power(board_id, consumption=power, timestamp=timestamp):
        return jsonify({"error": "Board not registered"}), 404
    
    return jsonify({
        "status": "success",
        "updated_by": getattr(request, 'user', {}).get('name', 'Unknown')
    })

@app.route('/poll_binary/<int:board_id>', methods=['GET'])
@require_board_auth
def poll_binary(board_id):
    """Optimized binary poll endpoint for ESP32"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        status = user_game_state.get_board_status(board_id)
        if not status:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        # Pack response using the new protocol
        response = BoardBinaryProtocol.pack_poll_response(
            round_num=status.get('r', 0),
            score=status.get('s', 0),
            generation=status.get('g'),
            consumption=status.get('c'),
            round_type=status.get('rt', 'day'),
            game_active=status.get('game_active', False),
            expecting_data=status.get('expecting_data', False),
            building_table_version=user_game_state.get_building_table_version()
        )
        
        return response, 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        return b'PROTOCOL_ERROR', 500, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        return b'INTERNAL_ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/poll/<int:board_id>', methods=['GET'])
@require_board_auth
def poll(board_id):
    """Legacy JSON poll endpoint (deprecated, use /poll_binary)"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    status = user_game_state.get_board_status(board_id)
    if not status:
        return jsonify({"error": "Board not found"}), 404
    
    return jsonify(status)

# New Board Endpoints for ESP32 Boards

@app.route('/prod_vals', methods=['GET'])
@require_board_auth
def get_production_values():
    """Binary endpoint - Get power plant production ranges"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        ranges = user_game_state.get_power_plant_ranges()
        
        # Pack as binary: count(1) + [id(4) + min(4) + max(4)] * count
        data = struct.pack('B', len(ranges))  # count as uint8
        
        for plant_id, (min_power, max_power) in ranges.items():
            data += struct.pack('>I', plant_id)      # plant_id as uint32 big-endian
            data += struct.pack('>i', min_power)     # min_power as int32 big-endian
            data += struct.pack('>i', max_power)     # max_power as int32 big-endian
            
        return data, 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/cons_vals', methods=['GET'])
@require_board_auth
def get_consumption_values():
    """Binary endpoint - Get consumer consumption values"""
    try:
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        consumption = user_game_state.get_consumer_consumption()
        
        # Pack as binary: count(1) + [id(4) + consumption(4)] * count
        data = struct.pack('B', len(consumption))  # count as uint8
        
        for consumer_id, consumption_val in consumption.items():
            data += struct.pack('>I', consumer_id)      # consumer_id as uint32 big-endian
            data += struct.pack('>i', consumption_val)  # consumption as int32 big-endian
            
        return data, 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/post_vals', methods=['POST'])
@require_board_auth
def post_values():
    """Binary endpoint - Board posts current production and consumption"""
    try:
        data = request.get_data()
        if len(data) < 8:
            return b'INVALID_DATA', 400, {'Content-Type': 'application/octet-stream'}
        
        # Unpack: production(4) + consumption(4)
        production, consumption = struct.unpack('>ii', data[:8])
        
        # Get board ID from authentication
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board_id = user_game_state.get_board_id_from_username(username)
        if not board_id:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Update board power
        timestamp = int(time.time())
        if not user_game_state.update_board_power(board_id, generation=production, 
                                           consumption=consumption, timestamp=timestamp):
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
        return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
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
        
        # Get board ID from authentication
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board_id = user_game_state.get_board_id_from_username(username)
        if not board_id:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Update board's connected power plants
        if board_id in user_game_state.boards:
            user_game_state.boards[board_id].set_connected_power_plants(power_plants)
            return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        else:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
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
        
        # Get board ID from authentication
        user = getattr(request, 'user', {})
        username = user.get('username', '')
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board_id = user_game_state.get_board_id_from_username(username)
        if not board_id:
            return b'INVALID_BOARD', 400, {'Content-Type': 'application/octet-stream'}
        
        # Update board's connected consumers
        if board_id in user_game_state.boards:
            user_game_state.boards[board_id].set_connected_consumers(consumers)
            return b'OK', 200, {'Content-Type': 'application/octet-stream'}
        else:
            return b'BOARD_NOT_FOUND', 404, {'Content-Type': 'application/octet-stream'}
        
    except Exception as e:
        return b'ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/register', methods=['POST'])
@require_board_auth
def register():
    """Enhanced board registration endpoint - now supports both JSON and binary"""
    # Check if it's binary data
    content_type = request.headers.get('Content-Type', '')
    if 'application/octet-stream' in content_type:
        # Handle as binary registration
        try:
            data = request.get_data()
            board_id, board_name, board_type = BoardBinaryProtocol.unpack_registration_request(data)
            
            # Validate board_id
            if board_id <= 0:
                response = BoardBinaryProtocol.pack_registration_response(False, "Invalid board ID")
                return response, 400, {'Content-Type': 'application/octet-stream'}
            
            # Get user's game state
            user_game_state = get_user_game_state(request.user)
            
            # Register the board
            board = user_game_state.register_board(board_id, board_name, board_type)
            
            response = BoardBinaryProtocol.pack_registration_response(True, "Registration successful")
            return response, 200, {'Content-Type': 'application/octet-stream'}
            
        except BinaryProtocolError as e:
            response = BoardBinaryProtocol.pack_registration_response(False, str(e))
            return response, 400, {'Content-Type': 'application/octet-stream'}
        except Exception as e:
            response = BoardBinaryProtocol.pack_registration_response(False, "Internal error")
            return response, 500, {'Content-Type': 'application/octet-stream'}
    else:
        # Handle as JSON registration (legacy)
        data = request.get_json()
        board_id = data.get('board_id')
        board_name = data.get('board_name')
        board_type = data.get('board_type', 'generic')
        
        if not board_id:
            return jsonify({"error": "board_id is required"}), 400
        
        # Get user's game state
        user_game_state = get_user_game_state(request.user)
        
        board = user_game_state.register_board(board_id, board_name, board_type)
        
        return jsonify({
            "status": "success",
            "message": f"Board {board_id} registered successfully",
            "registered_by": getattr(request, 'user', {}).get('name', 'Unknown')
        })

# Frontend/Lecturer Endpoints

@app.route('/scenarios', methods=['GET'])
@require_lecturer_auth
def get_scenarios():
    """Get list of available scenarios"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    scenarios = user_game_state.get_scenarios()
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
    
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    if user_game_state.start_game_with_scenario(scenario_id):
        user = getattr(request, 'user', {})
        lecturer_name = user.get('name', 'Unknown Lecturer')
        
        return jsonify({
            "status": "success", 
            "message": f"Game started with scenario {scenario_id}", 
            "started_by": lecturer_name,
            "scenario_id": scenario_id
        })
    else:
        return jsonify({"error": "Invalid scenario ID"}), 400

@app.route('/get_pdf', methods=['GET'])
@require_lecturer_auth
def get_pdf():
    """Get PDF URL for current scenario"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    pdf_url = user_game_state.get_current_pdf_url()
    if pdf_url:
        return jsonify({
            "success": True,
            "url": pdf_url
        })
    else:
        return jsonify({
            "success": True,
            "url": "https://example.com/default-lecture.pdf"  # Default PDF
        })

@app.route('/next_round', methods=['POST'])
@require_lecturer_auth 
def next_round():
    """Advance to next round"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    # Calculate and add scores for current round
    for board_id in user_game_state.boards:
        score = user_game_state.calculate_board_score(board_id)
        user_game_state.boards[board_id].add_round_score(score)
    
    user = getattr(request, 'user', {})
    lecturer_name = user.get('name', 'Unknown Lecturer')
    
    if user_game_state.next_round():
        return jsonify({
            "status": "success", 
            "round": user_game_state.current_round, 
            "advanced_by": lecturer_name
        })
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
    
    statistics = []
    
    for board_id, board in user_game_state.boards.items():
        stats = {
            "board_id": board_id,
            "board_name": board.name,
            "board_type": board.board_type,
            "current_generation": board.current_generation,
            "current_consumption": board.current_consumption,
            "total_score": board.total_score,
            "round_scores": board.round_scores,
            "connected_power_plants": board.connected_power_plants,
            "connected_consumers": board.connected_consumers,
            "last_update": board.last_update
        }
        statistics.append(stats)
    
    return jsonify({
        "success": True,
        "statistics": statistics,
        "game_status": {
            "current_round": user_game_state.current_round,
            "total_rounds": user_game_state.total_rounds,
            "game_active": user_game_state.game_active,
            "scenario": user_game_state.current_scenario.name if user_game_state.current_scenario else None
        }
    })

@app.route('/end_game', methods=['POST'])
@require_lecturer_auth
def end_game():
    """End the current game"""
    # Get user's game state
    user_game_state = get_user_game_state(request.user)
    
    user_game_state.game_active = False
    user_game_state.current_scenario = None
    user_game_state.current_scenario_round = 0
    
    user = getattr(request, 'user', {})
    lecturer_name = user.get('name', 'Unknown Lecturer')
    
    return jsonify({
        "status": "success",
        "message": "Game ended",
        "ended_by": lecturer_name
    })

@app.route('/pollforusers', methods=['GET'])
@require_lecturer_auth
def poll_for_users():
    """Endpoint for authenticated lecturers to get status of all boards"""
    all_boards = []
    
    for board_id in game_state.boards:
        status = game_state.get_board_status(board_id)
        if status:
            all_boards.append({
                "board_id": board_id,
                "board_name": game_state.boards[board_id].name,
                "board_type": game_state.boards[board_id].board_type,
                **status
            })
    
    # Parse user metadata
    user = getattr(request, 'user', {})
    user_metadata = {}
    if user.get('metadata'):
        try:
            user_metadata = json.loads(user['metadata'])
        except:
            user_metadata = {}
    
    return jsonify({
        "boards": all_boards,
        "game_status": {
            "current_round": game_state.current_round,
            "total_rounds": game_state.total_rounds,
            "round_type": game_state.get_current_round_type().value if game_state.game_active else None,
            "game_active": game_state.game_active
        },
        "lecturer_info": {
            "user_id": user.get('user_id'),
            "name": user.get('name', 'Unknown'),
            "department": user_metadata.get('department', 'Unknown')
        }
    })

@app.route('/game/start', methods=['POST'])
@require_lecturer_auth
def start_game_legacy():
    """Legacy game start endpoint (deprecated, use /start_game)"""
    game_state.start_game()
    user = getattr(request, 'user', {})
    user_metadata = {}
    if user.get('metadata'):
        try:
            user_metadata = json.loads(user['metadata'])
        except:
            user_metadata = {}
    
    lecturer_name = user.get('name', 'Unknown Lecturer')
    return jsonify({
        "status": "success", 
        "message": "Game started", 
        "started_by": lecturer_name,
        "lecturer_department": user_metadata.get('department', 'Unknown')
    })

@app.route('/game/next_round', methods=['POST'])
@require_lecturer_auth
def next_round_legacy():
    """Legacy next round endpoint (deprecated, use /next_round)"""
    # Calculate and add scores for current round
    for board_id in game_state.boards:
        score = game_state.calculate_board_score(board_id)
        game_state.boards[board_id].add_round_score(score)
    
    user = getattr(request, 'user', {})
    user_metadata = {}
    if user.get('metadata'):
        try:
            user_metadata = json.loads(user['metadata'])
        except:
            user_metadata = {}
    
    lecturer_name = user.get('name', 'Unknown Lecturer')
    
    if game_state.next_round():
        return jsonify({
            "status": "success", 
            "round": game_state.current_round, 
            "advanced_by": lecturer_name,
            "lecturer_department": user_metadata.get('department', 'Unknown')
        })
    else:
        return jsonify({
            "status": "game_finished", 
            "message": "All rounds completed", 
            "finished_by": lecturer_name,
            "lecturer_department": user_metadata.get('department', 'Unknown')
        })

@app.route('/game/status', methods=['GET'])
@optional_auth
def game_status():
    base_status = {
        "current_round": game_state.current_round,
        "total_rounds": game_state.total_rounds,
        "round_type": game_state.get_current_round_type().value if game_state.game_active else None,
        "game_active": game_state.game_active,
        "boards": len(game_state.boards)
    }
    
    # Add detailed information for authenticated users
    user = getattr(request, 'user', None)
    if user:
        user_metadata = {}
        if user.get('metadata'):
            try:
                user_metadata = json.loads(user['metadata'])
            except:
                user_metadata = {}
        
        user_type = user.get('user_type')
        if user_type == 'lecturer':
            base_status["board_details"] = [
                {
                    "board_id": board_id,
                    "name": board.name,
                    "type": board.board_type,
                    "current_generation": board.current_generation,
                    "current_consumption": board.current_consumption,
                    "total_score": board.total_score
                }
                for board_id, board in game_state.boards.items()
            ]
            base_status["lecturer_info"] = {
                "name": user.get('name', 'Unknown'),
                "department": user_metadata.get('department', 'Unknown')
            }
        elif user_type == 'board':
            # Boards get limited information
            base_status["board_info"] = {
                "name": user.get('name', 'Unknown'),
                "board_type": user_metadata.get('board_type', 'Unknown'),
                "location": user_metadata.get('location', 'Unknown')
            }
    
    return jsonify(base_status)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Docker and load balancers"""
    return jsonify({
        "status": "healthy",
        "service": "CoreAPI",
        "boards_registered": len(game_state.boards),
        "game_active": game_state.game_active,
        "current_round": game_state.current_round if game_state.game_active else None
    })

@app.route('/building_table', methods=['GET'])
@require_lecturer_auth
def get_building_table():
    """Get the building power consumption table for web UI"""
    table = game_state.get_building_table()
    version = game_state.get_building_table_version()
    
    return jsonify({
        'success': True,
        'table': table,
        'version': version
    })

@app.route('/building_table', methods=['POST'])
@require_lecturer_auth
def update_building_table():
    """Update the building power consumption table via web UI"""
    data = request.get_json()
    
    if not data or 'table' not in data:
        return jsonify({'error': 'Table data required'}), 400
    
    table = data['table']
    
    # Validate table format
    if not isinstance(table, dict):
        return jsonify({'error': 'Table must be a dictionary'}), 400
    
    # Convert keys to integers and validate values
    try:
        validated_table = {}
        for building_type_str, consumption in table.items():
            building_type = int(building_type_str)
            if building_type < 0 or building_type > 255:
                return jsonify({'error': f'Building type {building_type} out of range (0-255)'}), 400
            
            consumption_val = int(consumption)
            if consumption_val < -2147483648 or consumption_val > 2147483647:
                return jsonify({'error': f'Consumption value {consumption_val} out of range'}), 400
            
            validated_table[building_type] = consumption_val
            
    except ValueError as e:
        return jsonify({'error': f'Invalid data format: {str(e)}'}), 400
    
    # Update the table
    new_version = game_state.update_building_table(validated_table)
    
    return jsonify({
        'success': True,
        'message': 'Building table updated',
        'version': new_version
    })

@app.route('/building_table_binary', methods=['GET'])
@require_board_auth
def get_building_table_binary():
    """Get the building table in binary format for ESP32"""
    try:
        table = game_state.get_building_table()
        version = game_state.get_building_table_version()
        
        binary_data = BoardBinaryProtocol.pack_building_table(table, version)
        return binary_data, 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        return b'PROTOCOL_ERROR', 500, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        return b'INTERNAL_ERROR', 500, {'Content-Type': 'application/octet-stream'}

@app.route('/dashboard', methods=['GET'])
@require_auth
def dashboard():
    """Get user profile information for the dashboard"""
    user_info = request.user
    
    # Parse metadata if it's a JSON string
    metadata = {}
    if user_info.get('metadata'):
        try:
            metadata = json.loads(user_info['metadata'])
        except:
            metadata = {}
    
    return jsonify({
        'success': True,
        'user': {
            'id': user_info['user_id'],  # JWT payload uses 'user_id' not 'id'
            'username': user_info['username'],
            'name': user_info['name'],
            'user_type': user_info['user_type'],
            'metadata': metadata,
            'group_id': user_info.get('group_id', 'group1')  # Include group_id
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host="0.0.0.0", port=port)