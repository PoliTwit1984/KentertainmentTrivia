"""Test question flow and lifecycle."""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, socketio, games

# Constants for test configuration
TEST_TIMEOUT = 5  # seconds
TIME_LIMIT = 20  # seconds


@pytest.fixture(scope="function", autouse=True)
async def setup_and_teardown():
    """Setup and teardown for each test."""
    # Setup
    games.clear()

    yield

    # Teardown
    await asyncio.sleep(0.1)  # Allow any pending events to complete
    games.clear()


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
async def test_start_question(socket_client, mock_valid_token):
    """Test starting a new question round."""
    try:
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

        # Join room
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        join_response = await socket_client.get_received()
        assert any(event["name"] == "player_joined" for event in join_response)

        # Start the game
        await socket_client.emit("start_game", {
            "pin": "123456",
            "token": "valid_token"
        })
        start_response = await socket_client.get_received()
        assert any(event["name"] == "game_started" for event in start_response)

        # Start question
        question_data = {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        await socket_client.emit("start_question", {
            "pin": "123456",
            "token": "valid_token",
            "question": question_data
        })
        response = await socket_client.get_received()

        # Verify question started
        question_started_events = [
            event for event in response if event.get("name") == "question_started"
        ]
        assert len(question_started_events) > 0
        question_event = question_started_events[0]
        assert question_event["args"][0]["question"] == "Test question?"
        assert question_event["args"][0]["options"] == ["A", "B", "C", "D"]
        assert question_event["args"][0]["time_limit"] == TIME_LIMIT
        assert question_event["args"][0]["round"] == 1

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_submit_answer(socket_client, mock_valid_token):
    """Test submitting an answer within time limit."""
    try:
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

        # Join room
        await socket_client.emit("join_game", {
            "pin": "123456",
            "name": "Test Player"
        })
        join_response = await socket_client.get_received()
        assert any(event["name"] == "player_joined" for event in join_response)

        # Start the game
        await socket_client.emit("start_game", {
            "pin": "123456",
            "token": "valid_token"
        })
        start_response = await socket_client.get_received()
        assert any(event["name"] == "game_started" for event in start_response)

        # Start question
        question_data = {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        await socket_client.emit("start_question", {
            "pin": "123456",
            "token": "valid_token",
            "question": question_data
        })
        question_response = await socket_client.get_received()
        assert any(event["name"] == "question_started" for event in question_response)

        # Get player_id from the game state
        player_id = next(iter(games["123456"]["players"].keys()))

        # Submit answer
        await socket_client.emit("submit_answer", {
            "pin": "123456",
            "player_id": player_id,
            "answer": "A"
        })
        response = await socket_client.get_received()

        # Verify answer recorded
        answer_submitted_events = [
            event for event in response if event.get("name") == "answer_submitted"
        ]
        assert len(answer_submitted_events) > 0
        assert player_id in games["123456"]["answers"]
        assert games["123456"]["answers"][player_id]["answer"] == "A"
        assert games["123456"]["answers"][player_id]["time_taken"] <= TIME_LIMIT

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_question_timeout():
    """Test handling of question timeout."""
    try:
        # Create a game with an active question
        current_time = datetime.now(timezone.utc).timestamp()
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host_123",
            "status": "question",
            "players": {
                "player_1": {"name": "Test Player"}
            },
            "current_question": {
                "text": "Test question?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A"
            },
            "question_start_time": current_time - (TIME_LIMIT + 1),  # Question has expired
            "round": 1,
            "scores": {"player_1": 0},
            "streaks": {"player_1": 0},
            "answers": {},
            "max_players": 12
        }

        # Wait for timeout
        await asyncio.sleep(0.1)

        # Verify question state
        assert games["123456"]["status"] == "question"
        assert "player_1" not in games["123456"]["answers"]
        assert games["123456"]["scores"]["player_1"] == 0
        assert games["123456"]["streaks"]["player_1"] == 0

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_concurrent_answers(socket_client, mock_valid_token):
    """Test handling of concurrent answer submissions."""
    try:
        # Create a game with multiple players
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

        # Add players
        for i in range(3):
            await socket_client.emit("join_game", {
                "pin": "123456",
                "name": f"Player {i}"
            })
            await socket_client.get_received()

        # Start question
        question_data = {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        await socket_client.emit("start_question", {
            "pin": "123456",
            "token": "valid_token",
            "question": question_data
        })
        await socket_client.get_received()

        # Submit answers concurrently
        answer_tasks = []
        for player_id in games["123456"]["players"]:
            task = asyncio.create_task(socket_client.emit("submit_answer", {
                "pin": "123456",
                "player_id": player_id,
                "answer": "A"
            }))
            answer_tasks.append(task)

        # Wait for all answers
        await asyncio.gather(*answer_tasks)
        await asyncio.sleep(0.1)  # Allow answers to be processed

        # Verify answers
        assert len(games["123456"]["answers"]) == len(games["123456"]["players"])
        for player_id in games["123456"]["players"]:
            assert player_id in games["123456"]["answers"]
            assert games["123456"]["answers"][player_id]["answer"] == "A"
            assert games["123456"]["answers"][player_id]["time_taken"] <= TIME_LIMIT

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
