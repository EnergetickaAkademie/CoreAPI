from flask import Flask, request, jsonify
import pickle
from state import GameState

app = Flask(__name__)

# Game state
game_state = GameState()

@app.route('/register', methods=['POST'])
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
        "message": f"Board {board_id} registered successfully"
    })

@app.route('/power_generation', methods=['POST'])
def power_generation():
    data = request.get_json()
    board_id = data.get('board_id')
    power = data.get('power')
    timestamp = data.get('timestamp')
    
    if not game_state.update_board_power(board_id, generation=power, timestamp=timestamp):
        return jsonify({"error": "Board not registered"}), 404
    
    return jsonify({"status": "success"})

@app.route('/power_consumption', methods=['POST'])
def power_consumption():
    data = request.get_json()
    board_id = data.get('board_id')
    power = data.get('power')
    timestamp = data.get('timestamp')
    
    if not game_state.update_board_power(board_id, consumption=power, timestamp=timestamp):
        return jsonify({"error": "Board not registered"}), 404
    
    return jsonify({"status": "success"})

@app.route('/poll/<int:board_id>', methods=['GET'])
def poll(board_id):
    status = game_state.get_board_status(board_id)
    if not status:
        return jsonify({"error": "Board not found"}), 404
    
    return jsonify(status)

@app.route('/game/start', methods=['POST'])
def start_game():
    game_state.start_game()
    return jsonify({"status": "success", "message": "Game started"})

@app.route('/game/next_round', methods=['POST'])
def next_round():
    # Calculate and add scores for current round
    for board_id in game_state.boards:
        score = game_state.calculate_board_score(board_id)
        game_state.boards[board_id].add_round_score(score)
    
    if game_state.next_round():
        return jsonify({"status": "success", "round": game_state.current_round})
    else:
        return jsonify({"status": "game_finished", "message": "All rounds completed"})

@app.route('/game/status', methods=['GET'])
def game_status():
    return jsonify({
        "current_round": game_state.current_round,
        "total_rounds": game_state.total_rounds,
        "round_type": game_state.get_current_round_type().value,
        "game_active": game_state.game_active,
        "boards": len(game_state.boards)
    })

@app.route('/poll_binary/<int:board_id>', methods=['GET'])
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

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")