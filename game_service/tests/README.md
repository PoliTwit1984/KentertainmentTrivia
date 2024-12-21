# Game Service Test Suite Documentation

This document provides an overview of the test suite for the Team Trivia game service, including test scenarios, data requirements, and troubleshooting guidelines.

## Test Organization

The test suite is organized into multiple files, each focusing on specific aspects of the game service:

### 1. test_game.py
- Basic game operations
- Core functionality tests
- Simple success path scenarios

### 2. test_game_errors.py
- Error handling scenarios
- Edge cases
- Invalid input handling
- Permission checks
- State transition errors

### 3. test_game_flow.py
- Question timer expiration
- Score calculations
- Streak bonus handling
- Player disconnection scenarios
- Game progression

### 4. test_game_integration.py
- Full game rounds
- Multiple consecutive questions
- Game completion scenarios
- Concurrent games
- Performance testing

## Test Data Requirements

### Game Data Structure
```python
{
    "pin": "123456",              # 6-digit game PIN
    "host_id": "test_host_123",   # Host identifier
    "status": "active",           # Game status (lobby/active/question/completed)
    "players": {                  # Connected players
        "player_1": {
            "name": "Player 1"
        }
    },
    "current_question": {         # Current question data
        "text": "Question text",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    },
    "question_start_time": timestamp,  # UTC timestamp
    "round": 1,                   # Current round number
    "scores": {                   # Player scores
        "player_1": 1000
    },
    "streaks": {                  # Player answer streaks
        "player_1": 5
    },
    "answers": {                  # Current question answers
        "player_1": {
            "answer": "A",
            "time_taken": 5.0
        }
    },
    "max_players": 12            # Maximum players allowed
}
```

### Test Fixtures
- `setup_and_teardown`: Cleans game state before and after each test
- `client`: HTTP test client for REST endpoints
- `socket_client`: WebSocket test client for real-time events

### Mock Data
- Host tokens: Use `patch("app.verify_host_token")` for authentication
- Game PINs: Generated automatically or use "123456" for static tests
- Player IDs: Use format "player_1", "player_2", etc.
- Question data: Use simple A/B/C/D options with "A" as correct answer

## Common Test Scenarios

### 1. Game Creation and Setup
```python
# Create game with valid host token
with patch("app.verify_host_token") as mock:
    mock.return_value = (True, "test_host_123")
    response = client.post(
        "/game/create",
        headers={"Authorization": "Bearer valid_token"}
    )
```

### 2. Player Connections
```python
# Connect multiple players
socket_client.emit("join_game", {
    "pin": "123456",
    "name": "Player Name"
})
```

### 3. Question Flow
```python
# Setup question
games[pin]["status"] = "question"
games[pin]["current_question"] = {
    "text": "Test question?",
    "options": ["A", "B", "C", "D"],
    "correct_answer": "A"
}
games[pin]["question_start_time"] = datetime.now(timezone.utc).timestamp()

# Submit answer
socket_client.emit("submit_answer", {
    "pin": pin,
    "player_id": "player_1",
    "answer": "A"
})
```

## Performance Testing Guidelines

### 1. Concurrent Games
- Test with 5+ simultaneous games
- Each game should have 3+ active players
- Run multiple question rounds concurrently

### 2. Load Testing
- Maximum players (12) per game
- Rapid answer submissions
- Multiple concurrent operations
- Verify game state integrity

## Troubleshooting Guide

### Common Issues

1. Test Failures Due to Timing
   - Issue: Tests fail due to race conditions
   - Solution: Use `sleep(0.1)` after socket events
   - Example: After disconnections or state changes

2. Socket Event Handling
   - Issue: Missing socket responses
   - Solution: Clear received events after each emission
   - Example: `socket_client.get_received()`

3. Game State Corruption
   - Issue: Tests affecting each other
   - Solution: Use `setup_and_teardown` fixture
   - Verify: `games` and `active_players` cleared

4. Mock Authentication
   - Issue: Token verification fails
   - Solution: Properly patch `verify_host_token`
   - Example: See "Game Creation and Setup"

### Debug Strategies

1. Socket Events
```python
# Debug socket events
response = socket_client.get_received()
print("Socket response:", response)
```

2. Game State
```python
# Debug game state
game = games[pin]
print("Game status:", game["status"])
print("Players:", game["players"])
print("Scores:", game["scores"])
```

3. Concurrent Operations
```python
# Debug thread operations
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug(f"Thread {threading.current_thread().name}: Operation X")
```

## Adding New Tests

1. Choose Appropriate File
   - Core functionality → test_game.py
   - Error handling → test_game_errors.py
   - Game flow → test_game_flow.py
   - Integration/Performance → test_game_integration.py

2. Follow Test Structure
   - Use descriptive test names
   - Include setup, execution, verification
   - Clean up resources
   - Document edge cases

3. Test Data Guidelines
   - Use realistic data structures
   - Include edge cases
   - Document data requirements
   - Clean up test data

4. Performance Considerations
   - Avoid unnecessary sleeps
   - Clean up resources
   - Handle concurrent operations
   - Verify state integrity

## Running Tests

```bash
# Run all tests
pytest game_service/tests/

# Run specific test file
pytest game_service/tests/test_game_integration.py

# Run with coverage
pytest --cov=game_service game_service/tests/

# Run with detailed output
pytest -v game_service/tests/
```

## Maintenance

1. Regular Updates
   - Update test data for new features
   - Verify mock data accuracy
   - Update documentation
   - Review performance tests

2. Code Review Guidelines
   - Verify test coverage
   - Check edge cases
   - Review error handling
   - Validate concurrent operations

3. Performance Monitoring
   - Track test execution time
   - Monitor resource usage
   - Verify concurrent operations
   - Update load test parameters
