import pytest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, socketio, games


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Setup and teardown for each test."""
    games.clear()
    yield
    games.clear()


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


def test_start_question(socket_client, mock_valid_token):
    """Test starting a new question round."""
    # Create a game in lobby state
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "lobby",  # Start in lobby state
        "players": {},
        "max_players": 12,
        "current_question": None,
        "question_start_time": None,
        "round": 0,
        "scores": {},
        "streaks": {},
        "answers": {}
    }

    # Join room and wait for response
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    join_response = socket_client.get_received()
    print("Join response:", join_response)  # Debug print

    # Start the game
    socket_client.emit("start_game", {
        "pin": "123456",
        "token": "valid_token"
    })
    start_response = socket_client.get_received()
    print("Start game response:", start_response)  # Debug print

    # Start question
    question_data = {
        "text": "Test question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    }
    socket_client.emit("start_question", {
        "pin": "123456",
        "token": "valid_token",
        "question": question_data
    })
    response = socket_client.get_received()

    # Print debug information
    print("Response events:", [event.get("name") for event in response])
    print("Response data:", response)

    # Verify question started
    question_started_events = [
        event for event in response if event.get("name") == "question_started"
    ]
    assert len(question_started_events) > 0
    question_event = question_started_events[0]
    assert question_event["args"][0]["question"] == "Test question?"
    assert question_event["args"][0]["options"] == ["A", "B", "C", "D"]
    assert question_event["args"][0]["time_limit"] == 20
    assert question_event["args"][0]["round"] == 1


def test_submit_answer(socket_client, mock_valid_token):
    """Test submitting an answer within time limit."""
    # Create a game in lobby state
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
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

    # Join room and wait for response
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Test Player"
    })
    join_response = socket_client.get_received()
    print("Join response:", join_response)  # Debug print

    # Start the game
    socket_client.emit("start_game", {
        "pin": "123456",
        "token": "valid_token"
    })
    start_response = socket_client.get_received()
    print("Start game response:", start_response)  # Debug print

    # Start question
    question_data = {
        "text": "Test question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    }
    socket_client.emit("start_question", {
        "pin": "123456",
        "token": "valid_token",
        "question": question_data
    })
    question_response = socket_client.get_received()
    print("Question response:", question_response)  # Debug print

    # Get player_id from the game state
    player_id = next(iter(games["123456"]["players"].keys()))

    # Submit answer
    socket_client.emit("submit_answer", {
        "pin": "123456",
        "player_id": player_id,
        "answer": "A"
    })
    response = socket_client.get_received()

    # Print debug information
    print("Response events:", [event.get("name") for event in response])
    print("Response data:", response)

    # Verify answer recorded
    answer_submitted_events = [
        event for event in response if event.get("name") == "answer_submitted"
    ]
    assert len(answer_submitted_events) > 0
    assert player_id in games["123456"]["answers"]
    assert games["123456"]["answers"][player_id]["answer"] == "A"
    assert games["123456"]["answers"][player_id]["time_taken"] <= 20
