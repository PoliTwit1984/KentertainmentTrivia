import pytest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timezone
from gevent import sleep

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, socketio, games, active_players, handle_question_end


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Setup and teardown for each test."""
    games.clear()
    active_players.clear()
    yield
    games.clear()
    active_players.clear()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def socket_client():
    app.config["TESTING"] = True
    client = socketio.test_client(app)
    return client


@pytest.fixture
def mock_valid_token():
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        yield mock


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "healthy"
    assert response.json["service"] == "game"


def test_create_game(client, mock_valid_token):
    """Test game creation with valid host token."""
    response = client.post(
        "/game/create", headers={"Authorization": "Bearer valid_token"}
    )
    assert response.status_code == 200
    assert "pin" in response.json
    assert len(response.json["pin"]) == 6
    assert response.json["status"] == "created"


def test_create_game_invalid_token(client):
    """Test game creation with invalid token."""
    response = client.post(
        "/game/create", headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
    assert "error" in response.json


def test_game_status(client, mock_valid_token):
    """Test getting game status."""
    # Create a game first
    create_response = client.post(
        "/game/create", headers={"Authorization": "Bearer valid_token"}
    )
    pin = create_response.json["pin"]

    # Get status
    response = client.get(f"/game/{pin}/status")
    assert response.status_code == 200
    assert response.json["status"] == "lobby"
    assert response.json["player_count"] == 0
    assert isinstance(response.json["players"], list)


def test_game_status_not_found(client):
    """Test getting status of non-existent game."""
    response = client.get("/game/999999/status")
    assert response.status_code == 404
    assert "error" in response.json


def test_join_game(socket_client):
    """Test player joining a game."""
    # Create a game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host",
        "status": "lobby",
        "players": {},
        "max_players": 12,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {},
        "streaks": {},
        "answers": {}
    }

    # Join game
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    response = socket_client.get_received()

    assert len(response) > 0
    assert "player_joined" in [event["name"] for event in response]

    # Verify player was added
    assert len(games["123456"]["players"]) == 1
    player = list(games["123456"]["players"].values())[0]
    assert player["name"] == "Test Player"


def test_join_full_game(socket_client):
    """Test joining a full game."""
    # Create a full game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host",
        "status": "lobby",
        "players": {str(i): {} for i in range(12)},  # 12 players
        "max_players": 12
    }

    # Attempt to join
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Extra Player"
    })
    response = socket_client.get_received()

    error_responses = [
        event
        for event in response
        if event.get("args")
        and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Game is full"
    ]
    assert len(error_responses) > 0


def test_join_started_game(socket_client):
    """Test joining a game that has already started."""
    # Create a started game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host",
        "status": "active",  # Game already started
        "players": {},
        "max_players": 12
    }

    # Attempt to join
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Late Player"
    })
    response = socket_client.get_received()

    error_responses = [
        event
        for event in response
        if event.get("args")
        and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Game has already started"
    ]
    assert len(error_responses) > 0


def test_start_game(socket_client, mock_valid_token):
    """Test starting a game as host."""
    # Create a game with one player
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "lobby",
        "players": {"player_1": {"name": "Test Player"}},
        "max_players": 12
    }

    # Join room
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    socket_client.get_received()  # Clear join response

    # Start game
    socket_client.emit("start_game", {
        "pin": "123456",
        "token": "valid_token"
    })
    response = socket_client.get_received()

    game_started_events = [
        event for event in response if event["name"] == "game_started"
    ]
    assert len(game_started_events) > 0
    assert games["123456"]["status"] == "active"


def test_player_disconnect(socket_client):
    """Test player disconnection handling."""
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
        "max_players": 12,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {"player_1": 0},
        "streaks": {"player_1": 0},
        "answers": {}
    }

    # Simulate player connection
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    socket_client.get_received()  # Clear join response

    # Get client session ID and wait for join to complete
    sid = socket_client.eio_sid
    socket_client.get_received()  # Clear join response

    # Disconnect player
    socket_client.disconnect()
    sleep(0.1)  # Wait for disconnect to process

    # Verify player was removed
    assert len(games["123456"]["players"]) == 0
    assert sid not in active_players


def test_submit_late_answer(socket_client):
    """Test submitting an answer after time limit."""
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
        "max_players": 12
    }

    # Join room
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    socket_client.get_received()  # Clear join response

    # Submit late answer
    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": "player_1",
        "answer": "A"
    })
    response = socket_client.get_received()

    # Verify answer rejected
    error_responses = [
        event
        for event in response
        if event.get("args")
        and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Time expired"
    ]
    assert len(error_responses) > 0


@pytest.fixture
def app_context():
    with app.app_context(), app.test_request_context():
        yield


def test_question_end_scoring(socket_client, app_context):
    """Test score calculation at question end."""
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
        "max_players": 12
    }

    # End question and calculate scores
    handle_question_end("123456")

    # Verify scores
    game = games["123456"]
    assert game["streaks"]["player_1"] == 2  # Streak increased
    assert game["streaks"]["player_2"] == 3  # Streak increased
    assert game["streaks"]["player_3"] == 0  # Streak reset

    # Check base points + time bonus + streak bonus
    assert game["scores"]["player_1"] > game["scores"]["player_2"]  # Fast answer scores more
    assert game["scores"]["player_3"] == 0  # Wrong answer gets no points


def test_clear_test_data():
    """Clear test data after tests."""
    games.clear()
    active_players.clear()
