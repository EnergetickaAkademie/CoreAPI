from flask import Flask, request, jsonify
from flask_cors import CORS
import pickle
import os
import json
import time
from state import GameState
from simple_auth import require_lecturer_auth, require_board_auth, require_auth, optional_auth, auth
from binary_protocol import BoardBinaryProtocol, BinaryProtocolError

app = Flask(__name__)

# Enable CORS for all routes
CORS(app, origins=['http://localhost'], 
     allow_headers=['Content-Type', 'Authorization', 'X-Auth-Token'],
     supports_credentials=True)

# Game state
game_state = GameState()

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
        
        # Register the board
        board = game_state.register_board(board_id, board_name, board_type)
        
        response = BoardBinaryProtocol.pack_registration_response(True, "Registration successful")
        return response, 200, {'Content-Type': 'application/octet-stream'}
        
    except BinaryProtocolError as e:
        response = BoardBinaryProtocol.pack_registration_response(False, str(e))
        return response, 400, {'Content-Type': 'application/octet-stream'}
    except Exception as e:
        response = BoardBinaryProtocol.pack_registration_response(False, "Internal error")
        return response, 500, {'Content-Type': 'application/octet-stream'}

@app.route('/register', methods=['POST'])
@require_board_auth
def register():
    """Legacy JSON board registration endpoint (deprecated, use /register_binary)"""
    data = request.get_json()
    board_id = data.get('board_id')
    board_name = data.get('board_name')
    board_type = data.get('board_type', 'generic')
    
    if not board_id:
        return jsonify({"error": "board_id is required"}), 400
    
    board = game_state.register_board(board_id, board_name, board_type)
    
    return jsonify({
        "status": "success",
        "message": f"Board {board_id} registered successfully",
        "registered_by": getattr(request, 'user', {}).get('name', 'Unknown')
    })

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
        
        # Update board power
        if not game_state.update_board_power(board_id, generation=generation, 
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
    
    if not game_state.update_board_power(board_id, generation=power, timestamp=timestamp):
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
    
    if not game_state.update_board_power(board_id, consumption=power, timestamp=timestamp):
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
        status = game_state.get_board_status(board_id)
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
            expecting_data=status.get('expecting_data', False)
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
    status = game_state.get_board_status(board_id)
    if not status:
        return jsonify({"error": "Board not found"}), 404
    
    return jsonify(status)

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
def start_game():
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
def next_round():
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
            'metadata': metadata
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host="0.0.0.0", port=port)