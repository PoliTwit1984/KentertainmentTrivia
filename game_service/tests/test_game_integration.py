"""Integration and performance tests for game service."""
import pytest
from unittest.mock import patch
import sys
import os
from datetime import datetime, timezone
from gevent import sleep
import threading
import random

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


def test_full_game_round():
    """Test a complete game round from creation to completion."""
    print("\n=== Testing Full Game Round ===")

    # Create game
    with app.test_client() as client:
        with patch("app.verify_host_token") as mock:
            mock.return_value = (True, "test_host_123")
            response = client.post(
                "/game/create",
                headers={"Authorization": "Bearer valid_token"}
            )
            assert response.status_code == 200
            pin = response.json["pin"]

    # Connect multiple players
    socket_clients = []
    for i in range(3):
        client = socketio.test_client(app)
        client.emit("join_game", {
            "pin": pin,
            "name": f"Player {i+1}"
        })
        socket_clients.append(client)
        client.get_received()  # Clear join response

    # Start game
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        socket_clients[0].emit("start_game", {
            "pin": pin,
            "token": "valid_token"
        })
        for client in socket_clients:
            client.get_received()  # Clear start game response

    # Play multiple rounds
    for round_num in range(1, 4):
        # Start question
        games[pin]["status"] = "question"
        games[pin]["current_question"] = {
            "text": f"Question {round_num}?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        games[pin]["question_start_time"] = datetime.now(timezone.utc).timestamp()
        games[pin]["round"] = round_num

        # Players submit answers
        for i, client in enumerate(socket_clients):
            answer = "A" if i < 2 else "B"  # First two players answer correctly
            client.emit("submit_answer", {
                "pin": pin,
                "player_id": f"player_{i+1}",
                "answer": answer
            })
            client.get_received()  # Clear answer response

        # End question
        handle_question_end(pin)
        for client in socket_clients:
            client.get_received()  # Clear question end response

            # End question and verify state
            handle_question_end(pin)
            for client in socket_clients:
                client.get_received()  # Clear question end response

    # End game after all rounds are complete
    with patch("app.verify_host_token") as mock:
        mock.return_value = (True, "test_host_123")
        with app.test_client() as client:
            response = client.post(
                f"/game/{pin}/end",
                headers={"Authorization": "Bearer valid_token"}
            )
            assert response.status_code == 200
            assert response.json["status"] == "completed"

    # Verify final game state
    game = games[pin]
    assert game["status"] == "completed"
    assert all(score > 0 for score in game["scores"].values())
    assert len(game["scores"]) == 3
    assert game["scores"]["player_1"] > 0
    assert game["scores"]["player_2"] > 0
    assert game["scores"]["player_3"] > 0


def test_multiple_consecutive_questions():
    """Test handling of multiple consecutive questions."""
    print("\n=== Testing Multiple Consecutive Questions ===")

    # Create and setup game
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {
            "player_1": {"name": "Player 1"},
            "player_2": {"name": "Player 2"}
        },
        "current_question": None,
        "round": 0,
        "scores": {"player_1": 0, "player_2": 0},
        "streaks": {"player_1": 0, "player_2": 0},
        "max_players": 12
    }

    # Run 10 consecutive questions rapidly
    for i in range(10):
        # Start question
        games["123456"]["status"] = "question"
        games["123456"]["current_question"] = {
            "text": f"Question {i+1}?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()
        games["123456"]["round"] = i + 1
        games["123456"]["answers"] = {}

        # Simulate rapid answers
        games["123456"]["answers"] = {
            "player_1": {"answer": "A", "time_taken": 1},
            "player_2": {"answer": "A", "time_taken": 1}
        }

        # End question immediately
        handle_question_end("123456")

    # Verify game integrity after rapid questions
    game = games["123456"]
    assert game["round"] == 10
    assert all(score > 0 for score in game["scores"].values())
    assert all(streak >= 0 for streak in game["streaks"].values())


def test_game_completion_scenarios():
    """Test various game completion scenarios."""
    print("\n=== Testing Game Completion Scenarios ===")

    # Test normal completion
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {
            "player_1": {"name": "Player 1"},
            "player_2": {"name": "Player 2"}
        },
        "scores": {"player_1": 1000, "player_2": 500},
        "streaks": {"player_1": 5, "player_2": 2},
        "round": 10,
        "max_players": 12
    }

    with app.test_client() as client:
        with patch("app.verify_host_token") as mock:
            mock.return_value = (True, "test_host_123")
            response = client.post(
                "/game/123456/end",
                headers={"Authorization": "Bearer valid_token"}
            )
            assert response.status_code == 200
            assert games["123456"]["status"] == "completed"

        # Test completion with disconnected players
        games["234567"] = {
            "pin": "234567",
            "host_id": "test_host_123",
            "status": "active",
            "players": {"player_1": {"name": "Last Player"}},
            "scores": {"player_1": 1000},  # Only active player has score
            "streaks": {"player_1": 5},
            "round": 10,
            "current_question": None,
            "question_start_time": None,
            "answers": {},
            "max_players": 12
        }

    with app.test_client() as client:
        with patch("app.verify_host_token") as mock:
            mock.return_value = (True, "test_host_123")
            response = client.post(
                "/game/234567/end",
                headers={"Authorization": "Bearer valid_token"}
            )
            assert response.status_code == 200
            assert "player_2" not in games["234567"]["scores"]


def test_concurrent_games():
    """Test handling of multiple concurrent games."""
    print("\n=== Testing Concurrent Games ===")

    # Create multiple games
    game_pins = []
    with app.test_client() as client:
        with patch("app.verify_host_token") as mock:
            mock.return_value = (True, "test_host_123")
            for _ in range(5):
                response = client.post(
                    "/game/create",
                    headers={"Authorization": "Bearer valid_token"}
                )
                assert response.status_code == 200
                game_pins.append(response.json["pin"])

    # Function to simulate game activity
    def run_game(pin):
        # Add players
        for i in range(3):
            games[pin]["players"][f"player_{pin}_{i}"] = {
                "name": f"Player {i}"
            }
            games[pin]["scores"][f"player_{pin}_{i}"] = 0
            games[pin]["streaks"][f"player_{pin}_{i}"] = 0

        # Run questions
        for round_num in range(1, 4):
            games[pin]["status"] = "question"
            games[pin]["current_question"] = {
                "text": f"Question {round_num}?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A"
            }
            games[pin]["question_start_time"] = datetime.now(timezone.utc).timestamp()
            games[pin]["round"] = round_num
            games[pin]["answers"] = {}

            # Simulate answers
            for i in range(3):
                games[pin]["answers"][f"player_{pin}_{i}"] = {
                    "answer": random.choice(["A", "B", "C", "D"]),
                    "time_taken": random.uniform(1, 15)
                }

            handle_question_end(pin)

    # Run games concurrently
    threads = []
    for pin in game_pins:
        thread = threading.Thread(target=run_game, args=(pin,))
        thread.start()
        threads.append(thread)

    # Wait for all games to complete
    for thread in threads:
        thread.join()

    # Verify all games completed successfully
    for pin in game_pins:
        game = games[pin]
        assert game["round"] == 3
        assert len(game["scores"]) == 3
        assert all(score >= 0 for score in game["scores"].values())
        assert all(streak >= 0 for streak in game["streaks"].values())


def test_performance_under_load():
    """Test game performance under heavy load."""
    print("\n=== Testing Performance Under Load ===")

    # Create a game with maximum players
    games["123456"] = {
        "pin": "123456",
        "host_id": "test_host_123",
        "status": "active",
        "players": {},
        "scores": {},
        "streaks": {},
        "max_players": 12
    }

    # Add maximum number of players
    for i in range(12):
        player_id = f"player_{i}"
        games["123456"]["players"][player_id] = {"name": f"Player {i}"}
        games["123456"]["scores"][player_id] = 0
        games["123456"]["streaks"][player_id] = 0

    # Function to simulate rapid answer submission
    def submit_answers():
        for _ in range(10):  # Submit 10 answers rapidly
            player_id = f"player_{random.randint(0, 11)}"
            games["123456"]["answers"][player_id] = {
                "answer": random.choice(["A", "B", "C", "D"]),
                "time_taken": random.uniform(1, 15)
            }
            sleep(0.1)  # Small delay to simulate network latency

    # Start multiple threads to simulate concurrent answer submissions
    games["123456"]["status"] = "question"
    games["123456"]["current_question"] = {
        "text": "Performance test question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": "A"
    }
    games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()
    games["123456"]["round"] = 1
    games["123456"]["answers"] = {}

    threads = []
    for _ in range(5):  # 5 threads submitting answers
        thread = threading.Thread(target=submit_answers)
        thread.start()
        threads.append(thread)

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Verify game state integrity
    handle_question_end("123456")
    game = games["123456"]
    assert game["status"] in ["active", "question"]  # Status should be valid
    assert all(score >= 0 for score in game["scores"].values())  # Scores should be valid
    assert all(streak >= 0 for streak in game["streaks"].values())  # Streaks should be valid
