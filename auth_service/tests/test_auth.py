import pytest
import jwt
from datetime import datetime, timedelta
from app import app, hosts

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def auth_headers(client):
    # Register and login a test host
    test_host = {
        'email': 'test@example.com',
        'password': 'testpass123'
    }
    client.post('/host/register', json=test_host)
    response = client.post('/host/login', json=test_host)
    token = response.json['token']
    return {'Authorization': f'Bearer {token}'}

def test_health_check(client):
    """Test health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == 'healthy'
    assert response.json['service'] == 'auth'

def test_register_host(client):
    """Test host registration."""
    response = client.post('/host/register', json={
        'email': 'host@example.com',
        'password': 'securepass123'
    })
    assert response.status_code == 201
    assert 'host_id' in response.json
    assert response.json['message'] == 'Host registered successfully'

def test_register_duplicate_host(client):
    """Test registering a host with existing email."""
    host_data = {
        'email': 'duplicate@example.com',
        'password': 'testpass123'
    }
    # First registration
    client.post('/host/register', json=host_data)
    # Attempt duplicate registration
    response = client.post('/host/register', json=host_data)
    assert response.status_code == 409
    assert 'error' in response.json

def test_login_success(client):
    """Test successful host login."""
    host_data = {
        'email': 'login@example.com',
        'password': 'testpass123'
    }
    # Register host
    client.post('/host/register', json=host_data)
    # Login
    response = client.post('/host/login', json=host_data)
    assert response.status_code == 200
    assert 'token' in response.json
    assert 'host_id' in response.json

def test_login_invalid_credentials(client):
    """Test login with invalid credentials."""
    response = client.post('/host/login', json={
        'email': 'wrong@example.com',
        'password': 'wrongpass'
    })
    assert response.status_code == 401
    assert 'error' in response.json

def test_verify_valid_token(client, auth_headers):
    """Test token verification with valid token."""
    response = client.post('/host/verify', headers=auth_headers)
    assert response.status_code == 200
    assert response.json['valid'] is True
    assert 'host_id' in response.json

def test_verify_invalid_token(client):
    """Test token verification with invalid token."""
    invalid_token = jwt.encode(
        {'host_id': 'fake_id', 'exp': datetime.utcnow() + timedelta(hours=1)},
        'wrong_secret',
        algorithm='HS256'
    )
    headers = {'Authorization': f'Bearer {invalid_token}'}
    response = client.post('/host/verify', headers=headers)
    assert response.status_code == 401
    assert 'error' in response.json

def test_verify_expired_token(client):
    """Test token verification with expired token."""
    expired_token = jwt.encode(
        {'host_id': 'fake_id', 'exp': datetime.utcnow() - timedelta(hours=1)},
        app.config['JWT_SECRET_KEY'],
        algorithm='HS256'
    )
    headers = {'Authorization': f'Bearer {expired_token}'}
    response = client.post('/host/verify', headers=headers)
    assert response.status_code == 401
    assert 'error' in response.json

def test_missing_credentials(client):
    """Test login with missing credentials."""
    response = client.post('/host/login', json={})
    assert response.status_code == 400
    assert 'error' in response.json

def test_clear_test_data():
    """Clear test data after tests."""
    hosts.clear()
