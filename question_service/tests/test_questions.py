import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_auth_response():
    with patch('requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'host_id': 'test_host_1'}
        yield mock_post

@pytest.fixture
def valid_token():
    return 'valid_test_token'

@pytest.fixture
def mock_opentdb_response():
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
    return [{
        'question': 'Test Jeopardy question?',
        'answer': 'Test answer',
        'category': {'title': 'Test Category'}
    }]

def test_health_check(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    data = response.json
    assert data['status'] == 'healthy'
    assert data['service'] == 'question'

def test_create_question_bank_unauthorized(client):
    """Test creating question bank without token."""
    response = client.post('/questions/bank', json={'name': 'Test Bank'})
    assert response.status_code == 401

def test_create_question_bank(client, mock_auth_response, valid_token):
    """Test creating a new question bank."""
    response = client.post(
        '/questions/bank',
        json={'name': 'Test Bank', 'description': 'Test Description'},
        headers={'Authorization': f'Bearer {valid_token}'}
    )
    assert response.status_code == 200
    data = response.json
    assert 'id' in data
    assert data['status'] == 'created'

def test_get_question_bank_not_found(client):
    """Test getting non-existent question bank."""
    response = client.get('/questions/bank/nonexistent')
    assert response.status_code == 404

def test_add_question_to_bank(client, mock_auth_response, valid_token):
    """Test adding a question to a bank."""
    # First create a bank
    bank_response = client.post(
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
    response = client.post(
        f'/questions/bank/{bank_id}/questions',
        json=question_data,
        headers={'Authorization': f'Bearer {valid_token}'}
    )
    assert response.status_code == 200
    assert response.json['status'] == 'added'

def test_add_invalid_question(client, mock_auth_response, valid_token):
    """Test adding an invalid question."""
    # Create a bank
    bank_response = client.post(
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
    response = client.post(
        f'/questions/bank/{bank_id}/questions',
        json=invalid_question,
        headers={'Authorization': f'Bearer {valid_token}'}
    )
    assert response.status_code == 400

@patch('requests.get')
def test_get_opentdb_questions(mock_get, client):
    """Test fetching questions from OpenTDB."""
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

    response = client.get('/questions/external/opentdb')
    assert response.status_code == 200
    questions = response.json
    assert len(questions) == 1
    assert questions[0]['text'] == 'Test question?'
    assert len(questions[0]['options']) == 4
    assert 'Correct' in questions[0]['options']

@patch('requests.get')
def test_get_jservice_questions(mock_get, client):
    """Test fetching questions from Jservice."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [{
        'question': 'Test Jeopardy question?',
        'answer': 'Test answer',
        'category': {'title': 'Test Category'}
    }]

    response = client.get('/questions/external/jservice')
    assert response.status_code == 200
    questions = response.json
    assert len(questions) == 1
    assert questions[0]['text'] == 'Test Jeopardy question?'
    assert questions[0]['options'] == ['Test answer']
    assert questions[0]['correct_answer'] == 0

def test_get_game_questions(client, mock_auth_response, valid_token):
    """Test getting questions for a game."""
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

        response = client.get(
            '/questions/game/test_game_1',
            headers={'Authorization': f'Bearer {valid_token}'}
        )
        assert response.status_code == 200
        questions = response.json
        assert len(questions) == 2  # One from each source
        assert any(q['source'] == 'opentdb' for q in questions)
        assert any(q['source'] == 'jservice' for q in questions)
