"""Test question service functionality."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, AsyncMock
from app import app

# Constants for test configuration
TEST_TIMEOUT = 5  # seconds


@pytest.fixture(scope="function", autouse=True)
async def setup_and_teardown():
    """Setup and teardown for each test."""
    # Setup
    app.config['TESTING'] = True

    yield

    # Teardown
    await asyncio.sleep(0.1)  # Allow any pending events to complete


@pytest.fixture
async def client():
    """Create an async test client."""
    async with app.test_client() as client:
        yield client


@pytest.fixture
def mock_auth_response():
    """Mock authentication response."""
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'host_id': 'test_host_1'}
        yield mock_post


@pytest.fixture
def valid_token():
    """Provide a valid test token."""
    return 'valid_test_token'


@pytest.fixture
def mock_opentdb_response():
    """Mock OpenTDB API response."""
    return {
        'response_code': 0,
        'results': [{
            'question': 'Test question?',
            'correct_answer': 'Correct',
            'incorrect_answers': ['Wrong1', 'Wrong2', 'Wrong3'],
            'category': 'Test',
            'difficulty': 'medium'
        }]
    }


@pytest.fixture
def mock_jservice_response():
    """Mock Jservice API response."""
    return [{
        'question': 'Test Jeopardy question?',
        'answer': 'Test answer',
        'category': {'title': 'Test Category'}
    }]


@pytest.mark.asyncio
async def test_health_check(client):
    """Test health check endpoint."""
    try:
        response = await client.get('/health')
        assert response.status_code == 200
        data = response.json
        assert data['status'] == 'healthy'
        assert data['service'] == 'question'
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_create_question_bank_unauthorized(client):
    """Test creating question bank without token."""
    try:
        response = await client.post('/questions/bank', json={'name': 'Test Bank'})
        assert response.status_code == 401
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_create_question_bank(client, mock_auth_response, valid_token):
    """Test creating a new question bank."""
    try:
        response = await client.post(
            '/questions/bank',
            json={'name': 'Test Bank', 'description': 'Test Description'},
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        assert response.status_code == 200
        data = response.json
        assert 'id' in data
        assert data['status'] == 'created'
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_get_question_bank_not_found(client):
    """Test getting non-existent question bank."""
    try:
        response = await client.get('/questions/bank/nonexistent')
        assert response.status_code == 404
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_add_question_to_bank(client, mock_auth_response, valid_token):
    """Test adding a question to a bank."""
    try:
        # First create a bank
        bank_response = await client.post(
            '/questions/bank',
            json={'name': 'Test Bank'},
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        bank_id = bank_response.json['id']

        # Then add a question
        question_data = {
            'text': 'Test question?',
            'options': ['A', 'B', 'C', 'D'],
            'correct_answer': 0,
            'category': 'Test',
            'difficulty': 'medium',
            'source': 'custom'
        }
        response = await client.post(
            f'/questions/bank/{bank_id}/questions',
            json=question_data,
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        assert response.status_code == 200
        assert response.json['status'] == 'added'
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_add_invalid_question(client, mock_auth_response, valid_token):
    """Test adding an invalid question."""
    try:
        # Create a bank
        bank_response = await client.post(
            '/questions/bank',
            json={'name': 'Test Bank'},
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        bank_id = bank_response.json['id']

        # Try to add invalid question
        invalid_question = {
            'text': 'Test question?',
            # Missing required fields
        }
        response = await client.post(
            f'/questions/bank/{bank_id}/questions',
            json=invalid_question,
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        assert response.status_code == 400
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_get_opentdb_questions(client):
    """Test fetching questions from OpenTDB."""
    try:
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                'response_code': 0,
                'results': [{
                    'question': 'Test question?',
                    'correct_answer': 'Correct',
                    'incorrect_answers': ['Wrong1', 'Wrong2', 'Wrong3'],
                    'category': 'Test',
                    'difficulty': 'medium'
                }]
            }

            response = await client.get('/questions/external/opentdb')
            assert response.status_code == 200
            questions = response.json
            assert len(questions) == 1
            assert questions[0]['text'] == 'Test question?'
            assert len(questions[0]['options']) == 4
            assert 'Correct' in questions[0]['options']
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_get_jservice_questions(client):
    """Test fetching questions from Jservice."""
    try:
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [{
                'question': 'Test Jeopardy question?',
                'answer': 'Test answer',
                'category': {'title': 'Test Category'}
            }]

            response = await client.get('/questions/external/jservice')
            assert response.status_code == 200
            questions = response.json
            assert len(questions) == 1
            assert questions[0]['text'] == 'Test Jeopardy question?'
            assert questions[0]['options'] == ['Test answer']
            assert questions[0]['correct_answer'] == 0
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_get_game_questions(client, mock_auth_response, valid_token):
    """Test getting questions for a game."""
    try:
        with patch('requests.get') as mock_get:
            # Mock OpenTDB response
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.side_effect = [
                {
                    'response_code': 0,
                    'results': [{
                        'question': 'Test question?',
                        'correct_answer': 'Correct',
                        'incorrect_answers': ['Wrong1', 'Wrong2', 'Wrong3'],
                        'category': 'Test',
                        'difficulty': 'medium'
                    }]
                },
                [{
                    'question': 'Test Jeopardy question?',
                    'answer': 'Test answer',
                    'category': {'title': 'Test Category'}
                }]
            ]

            response = await client.get(
                '/questions/game/test_game_1',
                headers={'Authorization': f'Bearer {valid_token}'}
            )
            assert response.status_code == 200
            questions = response.json
            assert len(questions) == 2  # One from each source
            assert any(q['source'] == 'opentdb' for q in questions)
            assert any(q['source'] == 'jservice' for q in questions)
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_external_api_error_handling(client):
    """Test handling of external API errors."""
    try:
        with patch('requests.get') as mock_get:
            # Simulate API error
            mock_get.return_value.status_code = 500
            mock_get.return_value.json.side_effect = Exception("API Error")

            # Test OpenTDB error handling
            response = await client.get('/questions/external/opentdb')
            assert response.status_code == 503  # Service Unavailable
            assert 'error' in response.json

            # Test Jservice error handling
            response = await client.get('/questions/external/jservice')
            assert response.status_code == 503
            assert 'error' in response.json
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_concurrent_question_fetching(client):
    """Test fetching questions from multiple sources concurrently."""
    try:
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                'response_code': 0,
                'results': [{
                    'question': 'Test question?',
                    'correct_answer': 'Correct',
                    'incorrect_answers': ['Wrong1', 'Wrong2', 'Wrong3'],
                    'category': 'Test',
                    'difficulty': 'medium'
                }]
            }

            # Create multiple concurrent requests
            tasks = []
            for _ in range(5):
                task = asyncio.create_task(client.get('/questions/external/opentdb'))
                tasks.append(task)

            # Wait for all requests to complete
            responses = await asyncio.gather(*tasks)

            # Verify all requests succeeded
            for response in responses:
                assert response.status_code == 200
                questions = response.json
                assert len(questions) == 1
                assert questions[0]['text'] == 'Test question?'
    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
