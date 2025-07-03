# Power Management Game API

A Flask-based game API for managing power generation and consumption across multiple boards (like ESP32 devices). The game tracks power efficiency across multiple rounds with different scoring systems for day and night rounds.

## Features

- **Board Registration**: Register ESP32 boards with the system
- **Power Tracking**: Monitor power generation and consumption
- **Game Management**: Multi-round game with day/night cycles
- **Scoring System**: Advanced scoring based on power efficiency
- **ESP32 Optimized**: Minimal JSON responses and binary endpoints for low-memory devices
- **Object-Oriented Design**: Clean separation of concerns with state management

## Game Rules

### Scoring System
- **Perfect Match** (within 5% efficiency): 10 points
- **Over Production** (>105% efficiency): 4 points
- **Under Production** (90-95% efficiency): 
  - Day rounds: 1 point
  - Night rounds: 0 points (penalty)
- **Poor Performance** (<90% efficiency): 0 points

### Round Types
- **Day**: Expected solar generation, penalties for under-production
- **Night**: Minimal generation expected, stricter penalties

## Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Server**:
   ```bash
   python src/main.py
   ```

3. **Test the API**:
   ```bash
   python src/test_simple.py
   ```

## API Endpoints

### Game Management
- `POST /game/start` - Start a new game
- `POST /game/next_round` - Advance to next round
- `GET /game/status` - Get current game status

### Board Management
- `POST /register` - Register a new board
- `POST /power_generation` - Submit power generation data
- `POST /power_consumption` - Submit power consumption data
- `GET /poll/<board_id>` - Get board status (JSON, ESP32 optimized)
- `GET /poll_binary/<board_id>` - Get board status (binary, ultra-minimal)
- `POST /submit_binary` - Submit power data in binary format

## Usage Examples

### Register a Board
```bash
curl -X POST http://localhost:5000/register \
  -H "Content-Type: application/json" \
  -d '{"board_id": 1, "board_name": "Solar Panel A", "board_type": "solar"}'
```

### Submit Power Data
```bash
# Generation
curl -X POST http://localhost:5000/power_generation \
  -H "Content-Type: application/json" \
  -d '{"board_id": 1, "power": 98.5, "timestamp": "2025-07-03T10:00:00Z"}'

# Consumption
curl -X POST http://localhost:5000/power_consumption \
  -H "Content-Type: application/json" \
  -d '{"board_id": 1, "power": 100.0, "timestamp": "2025-07-03T10:01:00Z"}'
```

### Poll Board Status
```bash
curl http://localhost:5000/poll/1
```

Response (minimal fields for ESP32):
```json
{
  "r": 1,           // current round
  "s": 25,          // total score
  "g": 98.5,        // current generation
  "c": 100.0,       // current consumption
  "rt": "day"       // round type
}
```

### Start Game and Play
```bash
# Start the game
curl -X POST http://localhost:5000/game/start

# Submit power data for multiple boards
curl -X POST http://localhost:5000/power_generation \
  -H "Content-Type: application/json" \
  -d '{"board_id": 1, "power": 95.0}'

# Advance to next round (calculates scores)
curl -X POST http://localhost:5000/game/next_round
```

## ESP32 Integration

### Minimal JSON Response
The `/poll/<board_id>` endpoint returns minimal field names to save RAM:
- `r`: round number
- `s`: total score
- `g`: generation
- `c`: consumption
- `rt`: round type

### Binary Protocol
For ultra-low bandwidth, use binary endpoints:
- `GET /poll_binary/<board_id>`: Returns 12 bytes of binary data
- `POST /submit_binary`: Accepts binary power data

Binary format:
```
poll_binary response: [round(1), score(2), generation(4), consumption(4), round_type(1)]
submit_binary request: [board_id(4), generation(4), consumption(4), data_type(1)]
```

## Project Structure

```
CoreAPI/
├── src/
│   ├── main.py           # Flask API endpoints
│   ├── state.py          # Game state management (OOP)
│   ├── test_api.py       # Comprehensive pytest tests
│   └── test_simple.py    # Simple API tests
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Testing

### Run Comprehensive Tests
```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest src/test_api.py -v
```

### Run Simple Tests
```bash
# Make sure server is running first
python src/main.py

# In another terminal
python src/test_simple.py
```

### Test Coverage
The tests cover:
- Board registration and validation
- Power data submission
- Game state management
- Round advancement
- Score calculation for all scenarios
- Error handling
- Complete game flow

## Game Flow Example

1. **Setup**: Register all boards
2. **Start**: Begin the game (sets round 1)
3. **Play**: Each round:
   - Boards submit power generation/consumption data
   - Poll for current status
   - Advance round (calculates and stores scores)
4. **End**: Game ends after 10 rounds

## Scoring Examples

### Perfect Match (10 points)
- Generation: 98W, Consumption: 100W → 98% efficiency → 10 points

### Over Production (4 points)
- Generation: 120W, Consumption: 100W → 120% efficiency → 4 points

### Under Production - Day (1 point)
- Generation: 92W, Consumption: 100W → 92% efficiency → 1 point

### Under Production - Night (0 points)
- Generation: 92W, Consumption: 100W → 92% efficiency → 0 points (penalty)

## Development

### Adding New Features
1. Update `state.py` for new game logic
2. Add endpoints in `main.py`
3. Add tests in `test_api.py`
4. Update documentation

### Extending Scoring
Modify the `RoundConfig` reward matrices in `state.py` to change scoring rules.

## License

This project is licensed under the MIT License - see the LICENSE file for details.