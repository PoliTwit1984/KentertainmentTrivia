"""Test game service core functionality."""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, socketio, games, active_players, handle_question_end

# Constants for test configuration
TEST_TIMEOUT = 5  # seconds
MAX_PLAYERS = 12


@pytest.fixture(scope="function", autouse=True)
async def setup_and_teardown():
    """Setup and teardown for each test."""
    # Setup
    games.clear()
    active_players.clear()

    yield

    # Teardown
    await asyncio.sleep(0.1)  # Allow any pending events to complete
    games.clear()
    active_players.clear()


@pytest.fixture
async def socket_client():
    """Create an async socket client for testing."""
    app.config["TESTING"] = True
    client = socketio.AsyncClient()
    await client.connect(f'http://{app.config["HOST"]}:{app.config["PORT"]}')
    yield client
    if client.connected:
        await client.disconnect()


@pytest.fixture
def mock_valid_token():
    """Mock token validation."""
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        yield mock


@pytest.mark.asyncio
async def test_health_check():
    """Test health check endpoint."""
    try:
        async with app.test_client() as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json["status"] == "healthy"
            assert response.json["service"] == "game"
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_create_game(mock_valid_token):
    """Test game creation with valid host token."""
    try:
        async with app.test_client() as client:
            response = await client.post(
                "/game/create", headers={"Authorization": "Bearer valid_token"}
            )
            assert response.status_code == 200
            assert "pin" in response.json
            assert len(response.json["pin"]) == 6
            assert response.json["status"] == "created"
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_create_game_invalid_token():
    """Test game creation with invalid token."""
    try:
        async with app.test_client() as client:
            response = await client.post(
                "/game/create", headers={"Authorization": "Bearer invalid_token"}
            )
            assert response.status_code == 401
            assert "error" in response.json
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_game_status(mock_valid_token):
    """Test getting game status."""
    try:
        async with app.test_client() as client:
            # Create a game first
            create_response = await client.post(
                "/game/create", headers={"Authorization": "Bearer valid_token"}
            )
            pin = create_response.json["pin"]

            # Get status
            response = await client.get(f"/game/{pin}/status")
            assert response.status_code == 200
            assert response.json["status"] == "lobby"
            assert response.json["player_count"] == 0
            assert isinstance(response.json["players"], list)
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_game_status_not_found():
    """Test getting status of non-existent game."""
    try:
        async with app.test_client() as client:
            response = await client.get("/game/999999/status")
            assert response.status_code == 404
            assert "error" in response.json
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_join_game(socket_client):
    """Test player joining a game."""
    try:
        # Create a game
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host",
            "status": "lobby",
            "players": {},
            "max_players": MAX_PLAYERS,
            "current_question": None,
            "question_start_time": None,
            "round": 0,
            "scores": {},
            "streaks": {},
            "answers": {}
        }

        # Join game
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        response = await socket_client.get_received()

        assert len(response) > 0
        assert "player_joined" in [event["name"] for event in response]

        # Verify player was added
        assert len(games["123456"]["players"]) == 1
        player = list(games["123456"]["players"].values())[0]
        assert player["name"] == "Test Player"
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_join_full_game(socket_client):
    """Test joining a full game."""
    try:
        # Create a full game
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host",
            "status": "lobby",
            "players": {str(i): {} for i in range(MAX_PLAYERS)},
            "max_players": MAX_PLAYERS
        }

        # Attempt to join
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Extra Player"
        })
        response = await socket_client.get_received()

        error_responses = [
            event
            for event in response
            if event.get("args")
            and isinstance(event["args"][0], dict)
            and event["args"][0].get("error") == "Game is full"
        ]
        assert len(error_responses) > 0
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_join_started_game(socket_client):
    """Test joining a game that has already started."""
    try:
        # Create a started game
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host",
            "status": "active",  # Game already started
            "players": {},
            "max_players": MAX_PLAYERS
        }

        # Attempt to join
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Late Player"
        })
        response = await socket_client.get_received()

        error_responses = [
            event
            for event in response
            if event.get("args")
            and isinstance(event["args"][0], dict)
            and event["args"][0].get("error") == "Game has already started"
        ]
        assert len(error_responses) > 0
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_start_game(socket_client, mock_valid_token):
    """Test starting a game as host."""
    try:
        # Create a game with one player
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host_123",
            "status": "lobby",
            "players": {"player_1": {"name": "Test Player"}},
            "max_players": MAX_PLAYERS
        }

        # Join room
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        await socket_client.get_received()  # Clear join response

        # Start game
        await socket_client.emit("start_game", {
            "pin": "123456",
            "token": "valid_token"
        })
        response = await socket_client.get_received()

        game_started_events = [
            event for event in response if event["name"] == "game_started"
        ]
        assert len(game_started_events) > 0
        assert games["123456"]["status"] == "active"
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_player_disconnect(socket_client):
    """Test player disconnection handling."""
    try:
        # Create a game with a player
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host",
            "status": "lobby",
            "players": {
                "player_1": {
                    "id": "player_1",
                    "name": "Test Player"
                }
            },
            "max_players": MAX_PLAYERS,
            "current_question": None,
            "question_start_time": None,
            "round": 0,
            "scores": {"player_1": 0},
            "streaks": {"player_1": 0},
            "answers": {}
        }

        # Simulate player connection
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        await socket_client.get_received()  # Clear join response

        # Get client session ID
        sid = socket_client.eio_sid

        # Disconnect player
        await socket_client.disconnect()
        await asyncio.sleep(0.1)  # Wait for disconnect to process

        # Verify player was removed
        assert len(games["123456"]["players"]) == 0
        assert sid not in active_players
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_submit_late_answer(socket_client):
    """Test submitting an answer after time limit."""
    try:
        current_time = datetime.now(timezone.utc).timestamp()

        # Create an active game with an expired question
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host_123",
            "status": "active",
            "players": {"player_1": {"name": "Test Player"}},
            "current_question": {
                "text": "Test question?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A"
            },
            "question_start_time": current_time - 25,  # 25 seconds ago
            "round": 1,
            "scores": {"player_1": 0},
            "streaks": {"player_1": 0},
            "answers": {},
            "max_players": MAX_PLAYERS
        }

        # Join room
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        await socket_client.get_received()  # Clear join response

        # Submit late answer
        await socket_client.emit("submit_answer", {
            "pin": "123456",
            "player_id": "player_1",
            "answer": "A"
        })
        response = await socket_client.get_received()

        # Verify answer rejected
        error_responses = [
            event
            for event in response
            if event.get("args")
            and isinstance(event["args"][0], dict)
            and event["args"][0].get("error") == "Time expired"
        ]
        assert len(error_responses) > 0
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_question_end_scoring(socket_client):
    """Test score calculation at question end."""
    try:
        current_time = datetime.now(timezone.utc).timestamp()

        # Create an active game with submitted answers
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host_123",
            "status": "active",
            "players": {
                "player_1": {"name": "Fast Player"},
                "player_2": {"name": "Slow Player"},
                "player_3": {"name": "Wrong Player"}
            },
            "current_question": {
                "text": "Test question?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A"
            },
            "question_start_time": current_time,
            "round": 1,
            "scores": {"player_1": 0, "player_2": 0, "player_3": 0},
            "streaks": {"player_1": 1, "player_2": 2, "player_3": 3},
            "answers": {
                "player_1": {"answer": "A", "time_taken": 5},  # Fast correct
                "player_2": {"answer": "A", "time_taken": 15},  # Slow correct
                "player_3": {"answer": "B", "time_taken": 10}  # Wrong
            },
            "max_players": MAX_PLAYERS
        }

        # End question and calculate scores
        await asyncio.wait_for(handle_question_end("123456"), timeout=TEST_TIMEOUT)

        # Verify scores
        game = games["123456"]
        assert game["streaks"]["player_1"] == 2  # Streak increased
        assert game["streaks"]["player_2"] == 3  # Streak increased
        assert game["streaks"]["player_3"] == 0  # Streak reset

        # Check base points + time bonus + streak bonus
        assert game["scores"]["player_1"] > game["scores"]["player_2"]  # Fast answer scores more
        assert game["scores"]["player_3"] == 0  # Wrong answer gets no points
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
