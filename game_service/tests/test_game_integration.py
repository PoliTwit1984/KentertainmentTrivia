"""Integration and performance tests for game service."""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
import sys
import os
from datetime import datetime, timezone
import random

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


@pytest.mark.asyncio
async def test_full_game_round():
    """Test a complete game round from creation to completion."""
    try:
        # Create game
        async with app.test_client() as client:
            with patch("app.verify_host_token") as mock:
                mock.return_value = (True, "test_host_123")
                response = await client.post(
                    "/game/create",
                    headers={"Authorization": "Bearer valid_token"}
                )
                assert response.status_code == 200
                pin = response.json["pin"]

        # Connect multiple players
        socket_clients = []
        for i in range(3):
            client = socketio.AsyncClient()
            await client.connect(f'http://{app.config["HOST"]}:{app.config["PORT"]}')
            await client.emit("join_game", {
                "pin": pin,
                "name": f"Player {i+1}"
            })
            socket_clients.append(client)
            await client.get_received()  # Clear join response

        # Start game
        with patch("app.verify_host_token") as mock:
            mock.return_value = (True, "test_host_123")
            await socket_clients[0].emit("start_game", {
                "pin": pin,
                "token": "valid_token"
            })
            for client in socket_clients:
                await client.get_received()  # Clear start game response

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
            answer_tasks = []
            for i, client in enumerate(socket_clients):
                answer = "A" if i < 2 else "B"  # First two players answer correctly
                task = asyncio.create_task(client.emit("submit_answer", {
                    "pin": pin,
                    "player_id": f"player_{i+1}",
                    "answer": answer
                }))
                answer_tasks.append(task)
                await client.get_received()  # Clear answer response

            await asyncio.gather(*answer_tasks)

            # End question
            await asyncio.wait_for(handle_question_end(pin), timeout=TEST_TIMEOUT)
            for client in socket_clients:
                await client.get_received()  # Clear question end response

        # End game after all rounds are complete
        async with app.test_client() as client:
            with patch("app.verify_host_token") as mock:
                mock.return_value = (True, "test_host_123")
                response = await client.post(
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

        # Cleanup
        for client in socket_clients:
            await client.disconnect()

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_multiple_consecutive_questions():
    """Test handling of multiple consecutive questions."""
    try:
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
            "max_players": MAX_PLAYERS
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
            await asyncio.wait_for(handle_question_end("123456"), timeout=TEST_TIMEOUT)

        # Verify game integrity after rapid questions
        game = games["123456"]
        assert game["round"] == 10
        assert all(score > 0 for score in game["scores"].values())
        assert all(streak >= 0 for streak in game["streaks"].values())

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_game_completion_scenarios():
    """Test various game completion scenarios."""
    try:
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
            "max_players": MAX_PLAYERS
        }

        async with app.test_client() as client:
            with patch("app.verify_host_token") as mock:
                mock.return_value = (True, "test_host_123")
                response = await client.post(
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
                "max_players": MAX_PLAYERS
            }

            with patch("app.verify_host_token") as mock:
                mock.return_value = (True, "test_host_123")
                response = await client.post(
                    "/game/234567/end",
                    headers={"Authorization": "Bearer valid_token"}
                )
                assert response.status_code == 200
                assert "player_2" not in games["234567"]["scores"]

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_concurrent_games():
    """Test handling of multiple concurrent games."""
    try:
        # Create multiple games
        game_pins = []
        async with app.test_client() as client:
            with patch("app.verify_host_token") as mock:
                mock.return_value = (True, "test_host_123")
                for _ in range(5):
                    response = await client.post(
                        "/game/create",
                        headers={"Authorization": "Bearer valid_token"}
                    )
                    assert response.status_code == 200
                    game_pins.append(response.json["pin"])

        # Function to simulate game activity
        async def run_game(pin):
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

                await asyncio.wait_for(handle_question_end(pin), timeout=TEST_TIMEOUT)

        # Run games concurrently
        await asyncio.gather(*[run_game(pin) for pin in game_pins])

        # Verify all games completed successfully
        for pin in game_pins:
            game = games[pin]
            assert game["round"] == 3
            assert len(game["scores"]) == 3
            assert all(score >= 0 for score in game["scores"].values())
            assert all(streak >= 0 for streak in game["streaks"].values())

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_performance_under_load():
    """Test game performance under heavy load."""
    try:
        # Create a game with maximum players
        games["123456"] = {
            "pin": "123456",
            "host_id": "test_host_123",
            "status": "active",
            "players": {},
            "scores": {},
            "streaks": {},
            "max_players": MAX_PLAYERS
        }

        # Add maximum number of players
        for i in range(MAX_PLAYERS):
            player_id = f"player_{i}"
            games["123456"]["players"][player_id] = {"name": f"Player {i}"}
            games["123456"]["scores"][player_id] = 0
            games["123456"]["streaks"][player_id] = 0

        # Function to simulate rapid answer submission
        async def submit_answers():
            for _ in range(10):  # Submit 10 answers rapidly
                player_id = f"player_{random.randint(0, MAX_PLAYERS-1)}"
                games["123456"]["answers"][player_id] = {
                    "answer": random.choice(["A", "B", "C", "D"]),
                    "time_taken": random.uniform(1, 15)
                }
                await asyncio.sleep(0.1)  # Small delay to simulate network latency

        # Start multiple tasks to simulate concurrent answer submissions
        games["123456"]["status"] = "question"
        games["123456"]["current_question"] = {
            "text": "Performance test question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A"
        }
        games["123456"]["question_start_time"] = datetime.now(timezone.utc).timestamp()
        games["123456"]["round"] = 1
        games["123456"]["answers"] = {}

        # Run concurrent answer submissions
        await asyncio.gather(*[submit_answers() for _ in range(5)])

        # Verify game state integrity
        await asyncio.wait_for(handle_question_end("123456"), timeout=TEST_TIMEOUT)
        game = games["123456"]
        assert game["status"] in ["active", "question"]  # Status should be valid
        assert all(score >= 0 for score in game["scores"].values())  # Scores should be valid
        assert all(streak >= 0 for streak in game["streaks"].values())  # Streaks should be valid

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
