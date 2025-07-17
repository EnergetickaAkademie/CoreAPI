import pytest
import json
import struct
from main import app, game_state
from state import RoundType, PowerPlantType, ConsumerType

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def fresh_game_state():
    """Reset game state before each test"""
    game_state.boards.clear()
    game_state.current_round = 0
    game_state.game_active = False
    return game_state

def test_register_board(client, fresh_game_state):
    """Test board registration"""
    response = client.post('/register', 
                          json={'board_id': 1, 'board_name': 'Test Board', 'board_type': 'solar'})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'Board 1 registered successfully' in data['message']
    
    # Check if board is registered in game state
    assert 1 in game_state.boards
    assert game_state.boards[1].name == 'Test Board'
    assert game_state.boards[1].board_type == 'solar'

def test_register_board_missing_id(client, fresh_game_state):
    """Test board registration with missing board_id"""
    response = client.post('/register', json={'board_name': 'Test Board'})
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'board_id is required' in data['error']

def test_power_generation(client, fresh_game_state):
    """Test power generation endpoint"""
    # First register a board
    client.post('/register', json={'board_id': 1})
    
    # Test power generation
    response = client.post('/power_generation', 
                          json={'board_id': 1, 'power': 100.5, 'timestamp': '2025-07-03T10:00:00Z'})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    
    # Check if data is stored
    assert game_state.boards[1].current_generation == 100.5
    assert game_state.boards[1].last_update == '2025-07-03T10:00:00Z'

def test_power_generation_unregistered_board(client, fresh_game_state):
    """Test power generation for unregistered board"""
    response = client.post('/power_generation', 
                          json={'board_id': 999, 'power': 100.5})
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'Board not registered' in data['error']

def test_power_consumption(client, fresh_game_state):
    """Test power consumption endpoint"""
    # First register a board
    client.post('/register', json={'board_id': 1})
    
    # Test power consumption
    response = client.post('/power_consumption', 
                          json={'board_id': 1, 'power': 95.0, 'timestamp': '2025-07-03T10:05:00Z'})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    
    # Check if data is stored
    assert game_state.boards[1].current_consumption == 95.0
    assert game_state.boards[1].last_update == '2025-07-03T10:05:00Z'

def test_poll_board(client, fresh_game_state):
    """Test polling board status"""
    # Register and set up board
    client.post('/register', json={'board_id': 1})
    client.post('/power_generation', json={'board_id': 1, 'power': 100.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 95.0})
    
    # Start game
    client.post('/game/start')
    
    # Poll board status
    response = client.get('/poll/1')
    assert response.status_code == 200
    data = json.loads(response.data)
    
    # Check minimal field names for ESP32
    assert 'r' in data  # round
    assert 's' in data  # score
    assert 'g' in data  # generation
    assert 'c' in data  # consumption
    assert 'rt' in data  # round type
    
    assert data['r'] == 1
    assert data['g'] == 100.0
    assert data['c'] == 95.0
    assert data['rt'] in ['day', 'night']

def test_poll_unregistered_board(client, fresh_game_state):
    """Test polling unregistered board"""
    response = client.get('/poll/999')
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'Board not found' in data['error']

def test_start_game(client, fresh_game_state):
    """Test starting the game"""
    response = client.post('/game/start')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'Game started' in data['message']
    
    # Check game state
    assert game_state.game_active == True
    assert game_state.current_round == 1

def test_next_round(client, fresh_game_state):
    """Test advancing to next round"""
    # Register boards and start game
    client.post('/register', json={'board_id': 1})
    client.post('/register', json={'board_id': 2})
    client.post('/game/start')
    
    # Set some power values
    client.post('/power_generation', json={'board_id': 1, 'power': 100.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 98.0})  # Perfect score
    
    client.post('/power_generation', json={'board_id': 2, 'power': 80.0})
    client.post('/power_consumption', json={'board_id': 2, 'power': 70.0})  # Over production
    
    # Advance round
    response = client.post('/game/next_round')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert data['round'] == 2
    
    # Check scores were calculated
    assert len(game_state.boards[1].round_scores) == 1
    assert len(game_state.boards[2].round_scores) == 1

def test_game_status(client, fresh_game_state):
    """Test game status endpoint"""
    response = client.get('/game/status')
    assert response.status_code == 200
    data = json.loads(response.data)
    
    assert 'current_round' in data
    assert 'total_rounds' in data
    assert 'round_type' in data
    assert 'game_active' in data
    assert 'boards' in data
    
    assert data['current_round'] == 0
    assert data['total_rounds'] == 10
    assert data['game_active'] == False
    assert data['boards'] == 0

def test_score_calculation_perfect_match(client, fresh_game_state):
    """Test perfect score calculation (within 5%)"""
    client.post('/register', json={'board_id': 1})
    client.post('/game/start')
    
    # Perfect match (98% efficiency)
    client.post('/power_generation', json={'board_id': 1, 'power': 98.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 100.0})
    
    score = game_state.calculate_board_score(1)
    assert score == 10  # Perfect score

def test_score_calculation_over_production(client, fresh_game_state):
    """Test over production score"""
    client.post('/register', json={'board_id': 1})
    client.post('/game/start')
    
    # Over production (110% efficiency)
    client.post('/power_generation', json={'board_id': 1, 'power': 110.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 100.0})
    
    score = game_state.calculate_board_score(1)
    assert score == 4  # Over production score

def test_score_calculation_under_production_day(client, fresh_game_state):
    """Test under production score during day"""
    client.post('/register', json={'board_id': 1})
    client.post('/game/start')
    
    # Ensure we're in day round
    assert game_state.get_current_round_type() == RoundType.DAY
    
    # Under production (90% efficiency)
    client.post('/power_generation', json={'board_id': 1, 'power': 90.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 100.0})
    
    score = game_state.calculate_board_score(1)
    assert score == 1  # Under production score for day

def test_score_calculation_under_production_night(client, fresh_game_state):
    """Test under production score during night"""
    client.post('/register', json={'board_id': 1})
    client.post('/game/start')
    
    # Move to night round
    game_state.current_round = 2  # Should be night
    assert game_state.get_current_round_type() == RoundType.NIGHT
    
    # Under production (90% efficiency)
    client.post('/power_generation', json={'board_id': 1, 'power': 90.0})
    client.post('/power_consumption', json={'board_id': 1, 'power': 100.0})
    
    score = game_state.calculate_board_score(1)
    assert score == 0  # Under production score for night (penalty)

def test_complete_game_flow(client, fresh_game_state):
    """Test complete game flow from registration to finish"""
    # Register boards
    client.post('/register', json={'board_id': 1, 'board_name': 'Solar Panel A'})
    client.post('/register', json={'board_id': 2, 'board_name': 'Solar Panel B'})
    
    # Start game
    client.post('/game/start')
    
    # Play a few rounds
    for round_num in range(1, 4):
        # Set power values
        client.post('/power_generation', json={'board_id': 1, 'power': 100.0})
        client.post('/power_consumption', json={'board_id': 1, 'power': 98.0})
        
        client.post('/power_generation', json={'board_id': 2, 'power': 80.0})
        client.post('/power_consumption', json={'board_id': 2, 'power': 85.0})
        
        # Check poll results
        response = client.get('/poll/1')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['r'] == round_num
        
        # Advance round
        if round_num < 3:
            client.post('/game/next_round')
    
    # Check final scores
    assert game_state.boards[1].total_score > 0
    assert game_state.boards[2].total_score > 0

# Tests for new endpoints

def test_production_values_endpoint(client, fresh_game_state):
    """Test /prod_vals binary endpoint"""
    response = client.get('/prod_vals')
    assert response.status_code == 200
    assert response.content_type == 'application/octet-stream'
    
    # Check binary format: count(1) + [id(4) + min(4) + max(4)] * count
    data = response.data
    assert len(data) >= 1
    
    count = struct.unpack('B', data[:1])[0]
    assert count == len(PowerPlantType)
    
    # Verify the data structure
    expected_length = 1 + count * 12  # 1 byte count + count * (4+4+4) bytes
    assert len(data) == expected_length

def test_consumption_values_endpoint(client, fresh_game_state):
    """Test /cons_vals binary endpoint"""
    response = client.get('/cons_vals')
    assert response.status_code == 200
    assert response.content_type == 'application/octet-stream'
    
    # Check binary format: count(1) + [id(4) + consumption(4)] * count
    data = response.data
    assert len(data) >= 1
    
    count = struct.unpack('B', data[:1])[0]
    assert count == len(ConsumerType)
    
    # Verify the data structure
    expected_length = 1 + count * 8  # 1 byte count + count * (4+4) bytes
    assert len(data) == expected_length

def test_post_values_endpoint(client, fresh_game_state):
    """Test /post_vals binary endpoint"""
    # First register a board
    client.post('/register', json={'board_id': 1})
    
    # Test posting binary values
    post_data = struct.pack('>ii', 45, 25)  # 45W production, 25W consumption
    response = client.post('/post_vals', 
                          data=post_data,
                          content_type='application/octet-stream')
    assert response.status_code == 200
    assert response.data == b'OK'
    
    # Verify values were updated
    board = game_state.boards[1]
    assert board.current_generation == 45
    assert board.current_consumption == 25

def test_production_connected_endpoint(client, fresh_game_state):
    """Test /prod_connected binary endpoint"""
    # First register a board
    client.post('/register', json={'board_id': 1})
    
    # Test posting connected power plants
    power_plants_data = struct.pack('B', 2)  # 2 power plants
    power_plants_data += struct.pack('>Ii', PowerPlantType.FVE.value, 50)  # FVE with 50W
    power_plants_data += struct.pack('>Ii', PowerPlantType.WIND.value, 30)  # Wind with 30W
    
    response = client.post('/prod_connected', 
                          data=power_plants_data,
                          content_type='application/octet-stream')
    assert response.status_code == 200
    assert response.data == b'OK'
    
    # Verify values were updated
    board = game_state.boards[1]
    assert PowerPlantType.FVE.value in board.connected_power_plants
    assert board.connected_power_plants[PowerPlantType.FVE.value] == 50
    assert PowerPlantType.WIND.value in board.connected_power_plants
    assert board.connected_power_plants[PowerPlantType.WIND.value] == 30

def test_consumption_connected_endpoint(client, fresh_game_state):
    """Test /cons_connected binary endpoint"""
    # First register a board
    client.post('/register', json={'board_id': 1})
    
    # Test posting connected consumers
    consumers_data = struct.pack('B', 2)  # 2 consumers
    consumers_data += struct.pack('>I', ConsumerType.HOUSING.value)
    consumers_data += struct.pack('>I', ConsumerType.BAKERY.value)
    
    response = client.post('/cons_connected', 
                          data=consumers_data,
                          content_type='application/octet-stream')
    assert response.status_code == 200
    assert response.data == b'OK'
    
    # Verify values were updated
    board = game_state.boards[1]
    assert ConsumerType.HOUSING.value in board.connected_consumers
    assert ConsumerType.BAKERY.value in board.connected_consumers

def test_scenarios_endpoint(client, fresh_game_state):
    """Test /scenarios endpoint"""
    response = client.get('/scenarios')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    assert 'scenarios' in data
    assert len(data['scenarios']) > 0
    
    # Check scenario structure
    scenario = data['scenarios'][0]
    assert 'id' in scenario
    assert 'name' in scenario

def test_start_game_with_scenario(client, fresh_game_state):
    """Test /start_game endpoint with scenario"""
    response = client.post('/start_game', json={'scenario_id': 1})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'scenario_id' in data
    assert data['scenario_id'] == 1
    
    # Check game state
    assert game_state.game_active is True
    assert game_state.current_scenario is not None
    assert game_state.current_scenario.id == 1

def test_get_pdf_endpoint(client, fresh_game_state):
    """Test /get_pdf endpoint"""
    # Start game with scenario first
    client.post('/start_game', json={'scenario_id': 1})
    
    response = client.get('/get_pdf')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    assert 'url' in data
    assert data['url'].startswith('http')

def test_get_statistics_endpoint(client, fresh_game_state):
    """Test /get_statistics endpoint"""
    # Register a board and start game
    client.post('/register', json={'board_id': 1, 'board_name': 'Test Board'})
    client.post('/start_game', json={'scenario_id': 1})
    
    response = client.get('/get_statistics')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['success'] is True
    assert 'statistics' in data
    assert 'game_status' in data
    
    # Check statistics structure
    stats = data['statistics'][0]
    assert 'board_id' in stats
    assert 'board_name' in stats
    assert 'connected_power_plants' in stats
    assert 'connected_consumers' in stats

def test_end_game_endpoint(client, fresh_game_state):
    """Test /end_game endpoint"""
    # Start game first
    client.post('/start_game', json={'scenario_id': 1})
    assert game_state.game_active is True
    
    response = client.post('/end_game')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data['status'] == 'success'
    
    # Check game state
    assert game_state.game_active is False
    assert game_state.current_scenario is None

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
