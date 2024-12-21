"""Test game flow scenarios and edge cases."""
import pytest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timezone, timedelta
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
def socket_client():
    app.config["TESTING"] = True
    client = socketio.test_client(app)
    return client


def test_question_timer_expiration(socket_client):
    """Test behavior when question timer expires."""
    print("\n=== Testing Question Timer Expiration ===")

    # Create a game with an active question
    current_time = datetime.now(timezone.utc).timestamp()
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "question",
        "players": {
            "player_1": {"name": "Fast Player"},
            "player_2": {"name": "Slow Player"},
            "player_3": {"name": "No Answer"}
        },
        "current_question": {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        },
        "question_start_time": current_time - 20,  # Question started 20 seconds ago
        "round": 1,
        "scores": {"player_1": 0, "player_2": 0, "player_3": 0},
        "streaks": {"player_1": 0, "player_2": 0, "player_3": 0},
        "answers": {
            "player_1": {"answer": "A", "time_taken": 5},
            "player_2": {"answer": "A", "time_taken": 15}
            # player_3 hasn't answered
        },
        "max_players": 12
    }

    # Handle question end
    handle_question_end("123456")

    # Verify scores were calculated correctly
    game = games["123456"]
    assert game["scores"]["player_1"] > game["scores"]["player_2"]  # Fast answer scores more
    assert game["scores"]["player_3"] == 0  # No answer gets no points
    assert game["streaks"]["player_3"] == 0  # No answer breaks streak


def test_score_calculation_edge_cases(socket_client):
    """Test edge cases in score calculation."""
    print("\n=== Testing Score Calculation Edge Cases ===")

    current_time = datetime.now(timezone.utc).timestamp()
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "question",
        "players": {
            "player_1": {"name": "Perfect Player"},
            "player_2": {"name": "Last Second Player"},
            "player_3": {"name": "Zero Time Player"}
        },
        "current_question": {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        },
        "question_start_time": current_time - 20,
        "round": 1,
        "scores": {"player_1": 1000, "player_2": 500, "player_3": 0},
        "streaks": {"player_1": 5, "player_2": 0, "player_3": 0},
        "answers": {
            "player_1": {"answer": "A", "time_taken": 1},  # Almost instant answer
            "player_2": {"answer": "A", "time_taken": 19.99},  # Last possible moment
            "player_3": {"answer": "A", "time_taken": 0}  # Impossibly fast answer
        },
        "max_players": 12
    }

    # Handle question end
    handle_question_end("123456")

    # Verify edge case handling
    game = games["123456"]
    assert game["scores"]["player_1"] > game["scores"]["player_2"]  # Fast answer bonus
    assert game["scores"]["player_3"] == 0  # Invalid time gets no points
    assert game["streaks"]["player_1"] == 6  # Maintain long streak
    assert game["streaks"]["player_2"] == 1  # Start new streak
    assert game["streaks"]["player_3"] == 0  # Invalid answer breaks streak


def test_streak_bonus_calculations():
    """Test streak bonus calculations in various scenarios."""
    print("\n=== Testing Streak Bonus Calculations ===")

    current_time = datetime.now(timezone.utc).timestamp()
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "question",
        "players": {
            "player_1": {"name": "Streak Master"},
            "player_2": {"name": "Streak Breaker"},
            "player_3": {"name": "Streak Starter"}
        },
        "current_question": {
            "text": "Test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        },
        "question_start_time": current_time - 10,
        "round": 5,  # Multiple questions in
        "scores": {"player_1": 2000, "player_2": 1000, "player_3": 500},
        "streaks": {"player_1": 9, "player_2": 4, "player_3": 0},
        "answers": {
            "player_1": {"answer": "A", "time_taken": 5},  # Maintains streak
            "player_2": {"answer": "B", "time_taken": 5},  # Breaks streak
            "player_3": {"answer": "A", "time_taken": 5}   # Starts streak
        },
        "max_players": 12
    }

    # Handle first question to establish initial state
    handle_question_end("123456")

    # Verify initial state
    game = games["123456"]
    assert game["streaks"]["player_1"] == 10  # Extended streak
    assert game["streaks"]["player_2"] == 0   # Broken streak
    assert game["streaks"]["player_3"] == 1   # Started streak

    # Run two more questions with all correct answers
    for i in range(2):
        # Reset game state for next question
        game["status"] = "question"
        game["current_question"] = {
            "text": f"Question {i+2}?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        game["question_start_time"] = datetime.now(timezone.utc).timestamp()
        game["answers"] = {
            "player_1": {"answer": "A", "time_taken": 5},  # Maintains streak
            "player_2": {"answer": "A", "time_taken": 5},  # Rebuilds streak
            "player_3": {"answer": "A", "time_taken": 5}   # Builds streak
        }
        handle_question_end("123456")

    # Verify final streak calculations
    assert game["streaks"]["player_1"] == 12  # Extended streak further
    assert game["streaks"]["player_2"] == 2   # Rebuilt streak
    assert game["streaks"]["player_3"] == 3   # Built streak

    # Verify streak bonuses in scores
    initial_gaps = {
        "p1_p2": 1000,  # Initial gap between player 1 and 2
        "p2_p3": 500    # Initial gap between player 2 and 3
    }
    final_gaps = {
        "p1_p2": game["scores"]["player_1"] - game["scores"]["player_2"],
        "p2_p3": game["scores"]["player_2"] - game["scores"]["player_3"]
    }
    # Longer streaks should increase score gaps
    assert final_gaps["p1_p2"] > initial_gaps["p1_p2"]


def test_player_disconnection_scenarios(socket_client):
    """Test handling of player disconnections during different game phases."""
    print("\n=== Testing Player Disconnection Scenarios ===")

    # Setup game with multiple players
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {
            "player_1": {"name": "Stable Player"},
            "player_2": {"name": "Disconnecting Player"},
            "player_3": {"name": "Reconnecting Player"}
        },
        "current_question": None,
        "round": 0,
        "scores": {"player_1": 0, "player_2": 0, "player_3": 0},
        "streaks": {"player_1": 0, "player_2": 0, "player_3": 0},
        "answers": {},
        "max_players": 12
    }

    # Set up socket connection for player_2
    active_players[socket_client.eio_sid] = {
        'game_pin': '123456',
        'player_id': 'player_2'
    }

    # Test disconnection during question
    games["123456"]["status"] = "question"
    games["123456"]["current_question"] = {
        "text": "Test question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    }
    games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()

    # Store player_2's data for verification
    player_2_data = games["123456"]["players"]["player_2"]

    # Simulate player_2 disconnection
    socket_client.disconnect()  # Proper disconnect event
    sleep(0.1)  # Wait for disconnect to process

    # Verify disconnected player handling
    assert "player_2" not in games["123456"]["players"]
    assert "player_2" not in games["123456"]["scores"]
    assert "player_2" not in games["123456"]["streaks"]
    assert socket_client.eio_sid not in active_players

    # Verify disconnect event was emitted
    response = socket_client.get_received()
    player_left_events = [
        event for event in response
        if event.get("name") == "player_left"
        and event.get("args")
        and isinstance(event["args"][0], dict)
        and event["args"][0].get("player", {}).get("name") == "Disconnecting Player"
    ]
    assert len(player_left_events) > 0

    # Test reconnection
    socket_client.emit("join_game", {
        "pin": "123456",
        "name": "Reconnecting Player",
        "player_id": "player_3"  # Trying to reconnect
    })
    response = socket_client.get_received()

    # Verify reconnection handling
    game = games["123456"]
    if "player_3" in game["players"]:
        assert game["scores"]["player_3"] == 0  # Score reset on reconnect
        assert game["streaks"]["player_3"] == 0  # Streak reset on reconnect

    # Test host disconnection handling
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        socket_client.emit("disconnect_request")  # Simulate host disconnect
        sleep(0.1)  # Wait for disconnect to process

        # Verify game remains active without host
        assert games["123456"]["status"] != "ended"
        assert len(games["123456"]["players"]) > 0


def test_question_progression(socket_client):
    """Test progression through multiple questions with various timing scenarios."""
    print("\n=== Testing Question Progression ===")

    # Setup game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {
            "player_1": {"name": "Consistent Player"},
            "player_2": {"name": "Inconsistent Player"}
        },
        "current_question": None,
        "round": 0,
        "scores": {"player_1": 0, "player_2": 0},
        "streaks": {"player_1": 0, "player_2": 0},
        "answers": {},
        "max_players": 12
    }

    # Test multiple question rounds
    for round_num in range(1, 4):
        # Start new question
        games["123456"]["status"] = "question"
        games["123456"]["current_question"] = {
            "text": f"Question {round_num}?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()
        games["123456"]["round"] = round_num
        games["123456"]["answers"] = {}

        # Simulate different answer patterns
        if round_num == 1:
            # Both answer correctly
            games["123456"]["answers"] = {
                "player_1": {"answer": "A", "time_taken": 5},
                "player_2": {"answer": "A", "time_taken": 10}
            }
        elif round_num == 2:
            # Only player 1 answers
            games["123456"]["answers"] = {
                "player_1": {"answer": "A", "time_taken": 5}
            }
        else:
            # Different answers
            games["123456"]["answers"] = {
                "player_1": {"answer": "A", "time_taken": 5},
                "player_2": {"answer": "B", "time_taken": 5}
            }

        # End question and verify state
        handle_question_end("123456")

        # Verify game state after each round
        assert games["123456"]["round"] == round_num
        assert "current_question" in games["123456"]
        assert "answers" in games["123456"]

        # Verify score and streak progression
        if round_num > 1:
            assert games["123456"]["scores"]["player_1"] > games["123456"]["scores"]["player_2"]
            assert games["123456"]["streaks"]["player_1"] > games["123456"]["streaks"]["player_2"]
