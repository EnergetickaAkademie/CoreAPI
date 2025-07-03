import pytest
import json
from main import app, game_state
from state import RoundType

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

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
