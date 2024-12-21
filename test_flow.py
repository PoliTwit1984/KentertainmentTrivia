import pytest
import requests
import socketio
import time
import json
import os
import asyncio
from contextlib import asynccontextmanager

# Test configuration
AUTH_SERVICE = os.getenv('AUTH_SERVICE_URL', 'http://localhost:5001')
GAME_SERVICE = os.getenv('GAME_SERVICE_URL', 'http://localhost:5002')

# Test fixtures
@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for the test module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
async def auth_token():
    """Get authentication token for tests."""
    register_data = {
        "email": f"test_{int(time.time())}@example.com",
        "password": "test123"
    }

    # Register new host
    register_response = requests.post(
        f"{AUTH_SERVICE}/host/register",
        json=register_data
    )
    assert register_response.status_code == 201

    # Login and get token
    login_response = requests.post(
        f"{AUTH_SERVICE}/host/login",
        json=register_data
    )
    assert login_response.status_code == 200
    return login_response.json()['token']

@pytest.fixture(scope="module")
async def game_pin(auth_token):
    """Create a game and return its PIN."""
    create_response = requests.post(
        f"{GAME_SERVICE}/game/create",
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert create_response.status_code == 200
    return create_response.json()['pin']

@pytest.fixture
async def socket_client():
    """Create and yield a socket client, then cleanup."""
    sio = socketio.AsyncClient()
    yield sio
    if sio.connected:
        await sio.disconnect()

@pytest.mark.asyncio
async def test_host_flow(auth_token):
    """Test host authentication and game creation flow."""
    assert auth_token, "Authentication token should be valid"

    # Verify token is valid
    verify_response = requests.post(
        f"{AUTH_SERVICE}/host/verify",
        headers={'Authorization': f'Bearer {auth_token}'}
    )
    assert verify_response.status_code == 200
    assert verify_response.json()['valid'] is True

@pytest.mark.asyncio
async def test_player_flow(game_pin, socket_client):
    """Test player connection and game interaction flow."""
    assert game_pin, "Game PIN should be valid"

    # Set up event handlers
    events_received = []

    @socket_client.event
    def connect():
        events_received.append('connect')

    @socket_client.event
    def disconnect():
        events_received.append('disconnect')

    @socket_client.on('player_joined')
    def on_player_joined(data):
        events_received.append(('player_joined', data))

    @socket_client.on('game_started')
    def on_game_started(data):
        events_received.append(('game_started', data))

    # Connect to game service
    await socket_client.connect(GAME_SERVICE)
    assert 'connect' in events_received

    # Join game
    await socket_client.emit('join_game', {
        'pin': game_pin,
        'name': 'Test Player'
    })

    # Wait for join confirmation
    await asyncio.sleep(1)
    assert any(event[0] == 'player_joined' for event in events_received if isinstance(event, tuple))

@pytest.mark.asyncio
async def test_game_status(game_pin):
    """Test game status endpoint."""
    status_response = requests.get(f"{GAME_SERVICE}/game/{game_pin}/status")
    assert status_response.status_code == 200

    status_data = status_response.json()
    assert status_data['status'] in ['lobby', 'active']
    assert isinstance(status_data['player_count'], int)
    assert isinstance(status_data['players'], list)

@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for invalid game operations."""
    # Test joining non-existent game
    sio = socketio.AsyncClient()
    await sio.connect(GAME_SERVICE)

    with pytest.raises(Exception):
        await sio.emit('join_game', {
            'pin': '000000',
            'name': 'Test Player'
        })

    await sio.disconnect()

    # Test invalid game status
    response = requests.get(f"{GAME_SERVICE}/game/000000/status")
    assert response.status_code == 404
