#!/usr/bin/env python3
"""
Simple test script to verify API endpoints work correctly
Run with: python test_simple.py
"""

import requests
import json
import time

# Configuration
BASE_URL = "http://localhost:5000"

def test_api():
    print("🎮 Testing Power Management Game API")
    print("=" * 50)
    
    # Test 1: Register boards
    print("\n1. Testing board registration...")
    
    # Register first board
    response = requests.post(f"{BASE_URL}/register", 
                           json={"board_id": 1, "board_name": "Solar Panel A", "board_type": "solar"})
    print(f"Register Board 1: {response.status_code} - {response.json()}")
    
    # Register second board
    response = requests.post(f"{BASE_URL}/register", 
                           json={"board_id": 2, "board_name": "Solar Panel B", "board_type": "solar"})
    print(f"Register Board 2: {response.status_code} - {response.json()}")
    
    # Test 2: Start game
    print("\n2. Testing game start...")
    response = requests.post(f"{BASE_URL}/game/start")
    print(f"Start Game: {response.status_code} - {response.json()}")
    
    # Test 3: Check game status
    print("\n3. Testing game status...")
    response = requests.get(f"{BASE_URL}/game/status")
    print(f"Game Status: {response.status_code} - {response.json()}")
    
    # Test 4: Submit power data
    print("\n4. Testing power data submission...")
    
    # Board 1 - Perfect match (within 5%)
    requests.post(f"{BASE_URL}/power_generation", 
                 json={"board_id": 1, "power": 98.0, "timestamp": "2025-07-03T10:00:00Z"})
    requests.post(f"{BASE_URL}/power_consumption", 
                 json={"board_id": 1, "power": 100.0, "timestamp": "2025-07-03T10:01:00Z"})
    
    # Board 2 - Over production
    requests.post(f"{BASE_URL}/power_generation", 
                 json={"board_id": 2, "power": 120.0, "timestamp": "2025-07-03T10:00:00Z"})
    requests.post(f"{BASE_URL}/power_consumption", 
                 json={"board_id": 2, "power": 100.0, "timestamp": "2025-07-03T10:01:00Z"})
    
    print("Power data submitted for both boards")
    
    # Test 5: Poll board status
    print("\n5. Testing board polling...")
    
    response = requests.get(f"{BASE_URL}/poll/1")
    print(f"Poll Board 1: {response.status_code} - {response.json()}")
    
    response = requests.get(f"{BASE_URL}/poll/2")
    print(f"Poll Board 2: {response.status_code} - {response.json()}")
    
    # Test 6: Advance round
    print("\n6. Testing round advancement...")
    response = requests.post(f"{BASE_URL}/game/next_round")
    print(f"Next Round: {response.status_code} - {response.json()}")
    
    # Test 7: Check updated scores
    print("\n7. Testing updated scores after round...")
    
    response = requests.get(f"{BASE_URL}/poll/1")
    board1_data = response.json()
    print(f"Board 1 after round: {board1_data}")
    
    response = requests.get(f"{BASE_URL}/poll/2")
    board2_data = response.json()
    print(f"Board 2 after round: {board2_data}")
    
    # Test 8: Play a few more rounds
    print("\n8. Testing multiple rounds...")
    for round_num in range(2, 5):
        print(f"\nRound {round_num}:")
        
        # Submit different power values
        requests.post(f"{BASE_URL}/power_generation", 
                     json={"board_id": 1, "power": 95.0 + round_num})
        requests.post(f"{BASE_URL}/power_consumption", 
                     json={"board_id": 1, "power": 100.0})
        
        requests.post(f"{BASE_URL}/power_generation", 
                     json={"board_id": 2, "power": 85.0})
        requests.post(f"{BASE_URL}/power_consumption", 
                     json={"board_id": 2, "power": 100.0})
        
        # Check current status
        response = requests.get(f"{BASE_URL}/poll/1")
        print(f"Board 1 current: {response.json()}")
        
        # Advance round
        response = requests.post(f"{BASE_URL}/game/next_round")
        print(f"Round result: {response.json()}")
    
    # Test 9: Final game status
    print("\n9. Final game status...")
    response = requests.get(f"{BASE_URL}/game/status")
    print(f"Final Game Status: {response.json()}")
    
    print("\n✅ API Testing Complete!")
    print("=" * 50)
    
    # Test 10: Test error cases
    print("\n10. Testing error cases...")
    
    # Try to register board without ID
    response = requests.post(f"{BASE_URL}/register", json={"board_name": "Invalid Board"})
    print(f"Register without ID: {response.status_code} - {response.json()}")
    
    # Try to poll non-existent board
    response = requests.get(f"{BASE_URL}/poll/999")
    print(f"Poll non-existent board: {response.status_code} - {response.json()}")
    
    # Try to submit power for non-existent board
    response = requests.post(f"{BASE_URL}/power_generation", 
                           json={"board_id": 999, "power": 100.0})
    print(f"Power for non-existent board: {response.status_code} - {response.json()}")
    
    print("\n🎯 All tests completed!")

if __name__ == "__main__":
    print("Make sure the Flask server is running on http://localhost:5000")
    print("Start it with: python main.py")
    print("Then run this test script")
    
    try:
        test_api()
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to the API server.")
        print("Please make sure the server is running with: python main.py")
    except Exception as e:
        print(f"❌ Error during testing: {e}")
