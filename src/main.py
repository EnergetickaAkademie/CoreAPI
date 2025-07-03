from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage for demo purposes
data_store = {}
registered_boards = {}

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    board_id = data.get('board_id')
    board_name = data.get('board_name', f'Board {board_id}')
    board_type = data.get('board_type', 'generic')
    
    if not board_id:
        return jsonify({"error": "board_id is required"}), 400
    
    registered_boards[board_id] = {
        'board_name': board_name,
        'board_type': board_type,
        'registered_at': data.get('timestamp')
    }
    
    # Initialize data store for the board if it doesn't exist
    if board_id not in data_store:
        data_store[board_id] = {}
    
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
    
    if board_id not in data_store:
        data_store[board_id] = {}
    
    data_store[board_id]['generation'] = power
    data_store[board_id]['timestamp'] = timestamp
    
    return jsonify({"status": "success"})

@app.route('/power_consumption', methods=['POST'])
def power_consumption():
    data = request.get_json()
    board_id = data.get('board_id')
    power = data.get('power')
    timestamp = data.get('timestamp')
    
    if board_id not in data_store:
        data_store[board_id] = {}
    
    data_store[board_id]['consumption'] = power
    data_store[board_id]['timestamp'] = timestamp
    
    return jsonify({"status": "success"})

@app.route('/poll/<int:board_id>', methods=['GET'])
def poll(board_id):
    if board_id not in data_store:
        return jsonify({"error": "Board not found"}), 404
        
    return jsonify({
        "board_id": board_id,
        "generation": data_store[board_id].get('generation'),
        "consumption": data_store[board_id].get('consumption'),
        "timestamp": data_store[board_id].get('timestamp')
    })

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")