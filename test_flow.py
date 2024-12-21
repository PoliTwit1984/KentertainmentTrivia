import requests
import socketio
import time
import json

# Test configuration
AUTH_SERVICE = 'http://localhost:5001'
GAME_SERVICE = 'http://localhost:5002'

def test_host_flow():
    print("\n=== Testing Host Flow ===")

    # 1. Register host
    print("\n1. Registering host...")
    register_response = requests.post(
        f"{AUTH_SERVICE}/host/register",
        json={
            "email": "test@example.com",
            "password": "test123"
        }
    )
    print(f"Register Response: {register_response.status_code}")
    print(register_response.json())

    # 2. Login host
    print("\n2. Logging in host...")
    login_response = requests.post(
        f"{AUTH_SERVICE}/host/login",
        json={
            "email": "test@example.com",
            "password": "test123"
        }
    )
    print(f"Login Response: {login_response.status_code}")
    print(login_response.json())

    token = login_response.json().get('token')

    # 3. Create game
    print("\n3. Creating game...")
    create_game_response = requests.post(
        f"{GAME_SERVICE}/game/create",
        headers={'Authorization': f'Bearer {token}'}
    )
    print(f"Create Game Response: {create_game_response.status_code}")
    print(create_game_response.json())

    game_pin = create_game_response.json().get('pin')
    return token, game_pin

def test_player_flow(game_pin):
    print("\n=== Testing Player Flow ===")

    # Initialize Socket.IO client
    sio = socketio.Client()

    @sio.event
    def connect():
        print("\nConnected to game service")

    @sio.event
    def disconnect():
        print("\nDisconnected from game service")

    @sio.on('player_joined')
    def on_player_joined(data):
        print(f"\nPlayer joined event: {data}")

    @sio.on('game_started')
    def on_game_started(data):
        print(f"\nGame started event: {data}")

    # Connect to game service
    print("\n1. Connecting to game service...")
    sio.connect(GAME_SERVICE)

    # Join game
    print(f"\n2. Joining game with PIN {game_pin}...")
    # Join game with callback
    def on_join_response(data):
        print(f"Join Response: {data}")

    sio.emit('join_game', {
        'pin': game_pin,
        'name': 'Test Player'
    }, callback=on_join_response)

    return sio

def main():
    print("Waiting for services to start...")
    time.sleep(10)  # Give services time to start
    try:
        # Test host flow
        token, game_pin = test_host_flow()

        # Check game status
        print("\n=== Checking Game Status ===")
        status_response = requests.get(f"{GAME_SERVICE}/game/{game_pin}/status")
        print(f"Status Response: {status_response.status_code}")
        print(status_response.json())

        # Test player flow
        sio = test_player_flow(game_pin)

        # Keep connection alive briefly to see events
        time.sleep(5)  # Give more time to see all events

        # Cleanup
        sio.disconnect()

    except Exception as e:
        print(f"\nError during testing: {e}")

if __name__ == "__main__":
    main()
