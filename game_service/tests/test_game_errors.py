"""Test error scenarios and edge cases for game operations."""
import pytest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timezone
from gevent import sleep

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, socketio, games, active_players


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


def test_host_operations_invalid_token(client):
    """Test various host operations with invalid tokens."""
    print("\n=== Testing Host Operations with Invalid Tokens ===")

    # Create game with expired token
    with patch("app.verify_host_token") as mock:
        mock.return_value = (False, "Token expired")
        response = client.post(
            "/game/create", headers={"Authorization": "Bearer expired_token"}
        )
        assert response.status_code == 401
        assert "error" in response.json
        assert "expired" in response.json["error"].lower()

    # Test invalid token format
    response = client.post(
        "/game/create", headers={"Authorization": "InvalidFormat"}
    )
    assert response.status_code == 401
    assert "error" in response.json
    assert "invalid token format" in response.json["error"].lower()

    # Test missing token
    response = client.post("/game/create")
    assert response.status_code == 401
    assert "error" in response.json
    assert "missing or invalid token" in response.json["error"].lower()


def test_question_start_permissions(socket_client):
    """Test starting questions with various permission scenarios."""
    print("\n=== Testing Question Start Permissions ===")

    # Create a game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {"player_1": {"name": "Test Player"}},
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {"player_1": 0},
        "streaks": {"player_1": 0},
        "answers": {},
        "max_players": 12
    }

    # Test player trying to start question
    socket_client.emit("start_question", {
        "pin": "123456",
        "token": "player_token",  # Not a host token
        "question": {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Not authorized to start questions"
    ]
    assert len(error_responses) > 0

    # Test starting question in lobby state
    games["123456"]["status"] = "lobby"
    socket_client.emit("start_question", {
        "pin": "123456",
        "token": "valid_host_token"
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Game not in active state"
    ]
    assert len(error_responses) > 0


def test_answer_submission_edge_cases(socket_client):
    """Test edge cases for answer submission."""
    print("\n=== Testing Answer Submission Edge Cases ===")

    current_time = datetime.now(timezone.utc).timestamp()

    # Create a game
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
        "question_start_time": current_time,
        "round": 1,
        "scores": {"player_1": 0},
        "streaks": {"player_1": 0},
        "answers": {},
        "max_players": 12
    }

    # Test submitting answer for non-existent player
    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": "nonexistent_player",
        "answer": "A"
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Player not found"
    ]
    assert len(error_responses) > 0

    # Test submitting invalid answer option
    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": "player_1",
        "answer": "E"  # Not a valid option
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Invalid answer option"
    ]
    assert len(error_responses) > 0

    # Test submitting multiple answers
    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": "player_1",
        "answer": "A"
    })
    socket_client.get_received()  # Clear first response

    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": "player_1",
        "answer": "B"
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Answer already submitted"
    ]
    assert len(error_responses) > 0


def test_concurrent_player_actions(socket_client):
    """Test handling of concurrent player actions."""
    print("\n=== Testing Concurrent Player Actions ===")

    # Create a game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {},
        "max_players": 3,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {},
        "streaks": {},
        "answers": {}
    }

    # Simulate multiple players joining concurrently
    for i in range(5):  # Try to join more than max_players
        socket_client.emit("join_game", {
            "pin": "123456",
            "name": f"Player {i}"
        })
        socket_client.get_received()  # Clear response

    # Verify only max_players were allowed to join
    assert len(games["123456"]["players"]) <= 3

    # Test concurrent answer submissions
    games["123456"]["current_question"] = {
        "text": "Test question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    }
    games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()

    # Simulate concurrent answer submissions from multiple players
    for player_id in games["123456"]["players"]:
        socket_client.emit("submit_answer", {
            "pin": "123456",
            "player_id": player_id,
            "answer": "A"
        })
        socket_client.get_received()  # Clear response

    # Verify each player could only submit once
    assert len(games["123456"]["answers"]) == len(games["123456"]["players"])


def test_game_state_transitions(socket_client, client):
    """Test invalid game state transitions."""
    print("\n=== Testing Game State Transitions ===")

    # Create a game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "completed",  # Game already completed
        "players": {"player_1": {"name": "Test Player"}},
        "max_players": 12,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {"player_1": 0},
        "streaks": {"player_1": 0},
        "answers": {}
    }

    # Test starting a completed game
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        response = client.post(
            "/game/123456/start",
            headers={"Authorization": "Bearer valid_token"}
        )
        assert response.status_code == 400
        assert "error" in response.json
        assert "cannot start completed game" in response.json["error"].lower()

    # Test joining a completed game
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "New Player"
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Game is completed"
    ]
    assert len(error_responses) > 0


def test_malformed_data(socket_client):
    """Test handling of malformed data in requests."""
    print("\n=== Testing Malformed Data Handling ===")

    # Create a game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {"player_1": {"name": "Test Player"}},
        "max_players": 12,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {"player_1": 0},
        "streaks": {"player_1": 0},
        "answers": {}
    }

    # Test join with missing name
    socket_client.emit("join_game", {
        "pin": "123456"
        # Missing name field
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Missing required field: name"
    ]
    assert len(error_responses) > 0

    # Test answer submission with missing fields
    socket_client.emit("submit_answer", {
        "pin": "123456"
        # Missing player_id and answer
    })
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Missing required fields"
    ]
    assert len(error_responses) > 0

    # Test with invalid JSON
    socket_client.emit("join_game", "not_a_json_object")
    response = socket_client.get_received()
    error_responses = [
        event for event in response
        if event.get("args") and isinstance(event["args"][0], dict)
        and event["args"][0].get("error") == "Invalid request format"
    ]
    assert len(error_responses) > 0
