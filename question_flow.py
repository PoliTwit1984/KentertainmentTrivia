"""Test question service flow and integration."""
import pytest
import asyncio
import os
import json
import time
import aiohttp
from datetime import datetime, timezone

# Constants for test configuration
TEST_TIMEOUT = 5  # seconds
AUTH_SERVICE = os.getenv('AUTH_SERVICE_URL', 'http://localhost:5001')
QUESTION_SERVICE = os.getenv('QUESTION_SERVICE_URL', 'http://localhost:5003')


@pytest.fixture(scope="module")
async def http_client():
    """Create and cleanup aiohttp client session."""
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture(scope="module")
async def auth_token(http_client):
    """Get authentication token for tests."""
    try:
        # Register host
        register_data = {
            "email": f"test_{int(time.time())}@example.com",
            "password": "test123"
        }

        async with http_client.post(
            f"{AUTH_SERVICE}/host/register",
            json=register_data,
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 201
            register_result = await response.json()

        # Login and get token
        async with http_client.post(
            f"{AUTH_SERVICE}/host/login",
            json=register_data,
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            login_result = await response.json()
            return login_result['token']
    except Exception as e:
        pytest.fail(f"Failed to get auth token: {str(e)}")


@pytest.mark.asyncio
async def test_question_bank_creation(http_client, auth_token):
    """Test creating a question bank."""
    try:
        async with http_client.post(
            f"{QUESTION_SERVICE}/questions/bank",
            headers={'Authorization': f'Bearer {auth_token}'},
            json={
                "name": "Test Question Bank",
                "description": "A test question bank for trivia games"
            },
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            bank_data = await response.json()
            assert 'id' in bank_data
            return bank_data['id']
    except Exception as e:
        pytest.fail(f"Failed to create question bank: {str(e)}")


@pytest.mark.asyncio
async def test_add_custom_question(http_client, auth_token, bank_id):
    """Test adding a custom question to a bank."""
    try:
        question_data = {
            "text": "What is the capital of France?",
            "options": ["Paris", "London", "Berlin", "Madrid"],
            "correct_answer": 0,
            "category": "Geography",
            "difficulty": "easy",
            "source": "custom"
        }

        async with http_client.post(
            f"{QUESTION_SERVICE}/questions/bank/{bank_id}/questions",
            headers={'Authorization': f'Bearer {auth_token}'},
            json=question_data,
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            result = await response.json()
            assert result['status'] == 'added'
    except Exception as e:
        pytest.fail(f"Failed to add custom question: {str(e)}")


@pytest.mark.asyncio
async def test_external_apis(http_client):
    """Test integration with external question APIs."""
    try:
        # Test OpenTDB API
        async with http_client.get(
            f"{QUESTION_SERVICE}/questions/external/opentdb",
            params={'amount': '2'},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            opentdb_questions = await response.json()
            assert len(opentdb_questions) > 0

        # Test Jservice API
        async with http_client.get(
            f"{QUESTION_SERVICE}/questions/external/jservice",
            params={'count': '2'},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            jservice_questions = await response.json()
            assert len(jservice_questions) > 0
    except Exception as e:
        pytest.fail(f"Failed to fetch external questions: {str(e)}")


@pytest.mark.asyncio
async def test_game_questions(http_client, auth_token):
    """Test getting questions for a game."""
    try:
        async with http_client.get(
            f"{QUESTION_SERVICE}/questions/game/test_game_1",
            headers={'Authorization': f'Bearer {auth_token}'},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 200
            questions = await response.json()
            assert len(questions) > 0
            assert all('text' in q and 'options' in q for q in questions)
    except Exception as e:
        pytest.fail(f"Failed to get game questions: {str(e)}")


@pytest.mark.asyncio
async def test_question_flow(http_client):
    """Test complete question flow."""
    try:
        # Get auth token
        token = await auth_token(http_client)
        assert token, "Failed to get auth token"

        # Create question bank
        bank_id = await test_question_bank_creation(http_client, token)
        assert bank_id, "Failed to create question bank"

        # Add custom question
        await test_add_custom_question(http_client, token, bank_id)

        # Test external APIs
        await test_external_apis(http_client)

        # Test game questions
        await test_game_questions(http_client, token)

    except Exception as e:
        pytest.fail(f"Question flow test failed: {str(e)}")


@pytest.mark.asyncio
async def test_concurrent_question_fetching(http_client):
    """Test fetching questions concurrently."""
    try:
        # Create multiple concurrent requests
        tasks = []
        for _ in range(5):
            task = asyncio.create_task(http_client.get(
                f"{QUESTION_SERVICE}/questions/external/opentdb",
                params={'amount': '2'},
                timeout=TEST_TIMEOUT
            ))
            tasks.append(task)

        # Wait for all requests to complete
        responses = await asyncio.gather(*tasks)

        # Verify all requests succeeded
        for response in responses:
            assert response.status == 200
            async with response:
                questions = await response.json()
                assert len(questions) > 0
    except Exception as e:
        pytest.fail(f"Concurrent question fetching failed: {str(e)}")


@pytest.mark.asyncio
async def test_error_handling(http_client, auth_token):
    """Test error handling scenarios."""
    try:
        # Test invalid bank ID
        async with http_client.get(
            f"{QUESTION_SERVICE}/questions/bank/nonexistent",
            headers={'Authorization': f'Bearer {auth_token}'},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 404

        # Test invalid question data
        async with http_client.post(
            f"{QUESTION_SERVICE}/questions/bank/test_bank/questions",
            headers={'Authorization': f'Bearer {auth_token}'},
            json={"invalid": "data"},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 400

        # Test unauthorized access
        async with http_client.post(
            f"{QUESTION_SERVICE}/questions/bank",
            json={"name": "Test Bank"},
            timeout=TEST_TIMEOUT
        ) as response:
            assert response.status == 401
    except Exception as e:
        pytest.fail(f"Error handling test failed: {str(e)}")


@pytest.mark.asyncio
async def test_api_timeout_handling(http_client):
    """Test handling of API timeouts."""
    try:
        # Test with very short timeout
        with pytest.raises(asyncio.TimeoutError):
            async with http_client.get(
                f"{QUESTION_SERVICE}/questions/external/opentdb",
                timeout=0.001  # 1ms timeout
            ) as response:
                await response.json()
    except Exception as e:
        pytest.fail(f"Timeout handling test failed: {str(e)}")


if __name__ == "__main__":
    pytest.main([__file__, '-v', '--asyncio-mode=auto'])
