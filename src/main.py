from flask import Flask, request, jsonify
from flask_cors import CORS
import pickle
import os
import json
from state import GameState
from simple_auth import require_lecturer_auth, require_board_auth, require_auth, optional_auth, auth

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

@app.route('/register', methods=['POST'])
@require_board_auth
def register():
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

@app.route('/power_generation', methods=['POST'])
@require_board_auth
def power_generation():
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

@app.route('/poll/<int:board_id>', methods=['GET'])
@require_board_auth
def poll(board_id):
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

@app.route('/poll_binary/<int:board_id>', methods=['GET'])
@require_board_auth
def poll_binary(board_id):
    """Minimal binary response for ESP32 with limited RAM"""
    status = game_state.get_board_status(board_id)
    if not status:
        return b'', 404
    
    # Pack data into minimal binary format
    # Format: round(1 byte), score(2 bytes), generation(4 bytes), consumption(4 bytes), round_type(1 byte)
    try:
        import struct
        round_num = min(status['r'], 255)  # Max 255 rounds
        score = min(status['s'], 65535)    # Max score 65535
        generation = int(status['g'] * 10) if status['g'] else 0  # 1 decimal place precision
        consumption = int(status['c'] * 10) if status['c'] else 0  # 1 decimal place precision
        round_type = 1 if status['rt'] == 'day' else 0
        
        binary_data = struct.pack('>BHIIB', round_num, score, generation, consumption, round_type)
        return binary_data, 200, {'Content-Type': 'application/octet-stream'}
    except Exception:
        return b'', 500

@app.route('/submit_binary', methods=['POST'])
@require_board_auth
def submit_binary():
    """Accept binary data from ESP32 to save bandwidth"""
    try:
        import struct
        data = request.get_data()
        if len(data) < 13:  # Minimum expected size
            return b'', 400
        
        # Format: board_id(4 bytes), generation(4 bytes), consumption(4 bytes), data_type(1 byte)
        board_id, generation, consumption, data_type = struct.unpack('>IIIB', data[:13])
        
        # Convert back from integer representation
        generation = generation / 10.0 if generation > 0 else None
        consumption = consumption / 10.0 if consumption > 0 else None
        
        # Update the appropriate power value
        if data_type == 1:  # Generation only
            game_state.update_board_power(board_id, generation=generation)
        elif data_type == 2:  # Consumption only
            game_state.update_board_power(board_id, consumption=consumption)
        else:  # Both
            game_state.update_board_power(board_id, generation=generation, consumption=consumption)
        
        return b'OK', 200
    except Exception:
        return b'', 500

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