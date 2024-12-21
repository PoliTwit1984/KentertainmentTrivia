from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room, emit
import os
import random
import string
import requests
from datetime import datetime, timezone
from gevent import spawn_later, sleep

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# In-memory storage for development (replace with Cosmos DB in production)
games = {}
active_players = {}
question_timers = {}  # Store question timers for each game
player_scores = {}    # Store player scores and streaks

# Game configuration
QUESTION_TIME_LIMIT = 20  # seconds per question
POINTS_BASE = 1000        # base points for correct answer
POINTS_TIME_BONUS = 500   # max time bonus points
STREAK_BONUS = 100        # points per answer streak

# Configuration
AUTH_SERVICE_URL = os.environ.get('AUTH_SERVICE_URL', 'http://localhost:5001')

def generate_game_pin():
    """Generate a unique 6-digit game PIN."""
    while True:
        pin = ''.join(random.choices(string.digits, k=6))
        if pin not in games:
            return pin

def verify_host_token(token):
    """Verify host token with auth service."""
    try:
        response = requests.post(
            f"{AUTH_SERVICE_URL}/host/verify",
            headers={'Authorization': f'Bearer {token}'}
        )
        if response.status_code == 200:
            return True, response.json().get('host_id')
        elif response.status_code == 401:
            return False, "Token expired"
        else:
            return False, "Invalid token"
    except requests.RequestException:
        return False, "Authentication service unavailable"

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'service': 'game',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'features': {
            'game_management': True,
            'real_time_updates': True,
            'hot_reload': True
        }
    })

@app.route('/game/create', methods=['POST'])
def create_game():
    """Create a new game session."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token format'}), 401

    token = auth_header.split(' ')[1]
    is_valid, result = verify_host_token(token)

    if not is_valid:
        return jsonify({'error': result}), 401

    host_id = result
    game_pin = generate_game_pin()
    games[game_pin] = {
        'pin': game_pin,
        'host_id': host_id,
        'status': 'lobby',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'players': {},
        'max_players': 12,
        'current_question': None,
        'question_start_time': None,
        'round': 0,
        'scores': {},
        'streaks': {},
        'answers': {}
    }

    return jsonify({
        'pin': game_pin,
        'status': 'created'
    })

@app.route('/game/<pin>/status', methods=['GET'])
def game_status(pin):
    """Get game status and player list."""
    if pin not in games:
        return jsonify({'error': 'Game not found'}), 404

    game = games[pin]
    return jsonify({
        'status': game['status'],
        'player_count': len(game['players']),
        'players': list(game['players'].values())
    })

@app.route('/game/<pin>/start', methods=['POST'])
def start_game(pin):
    """Start a game session."""
    if pin not in games:
        return jsonify({'error': 'Game not found'}), 404

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token format'}), 401

    token = auth_header.split(' ')[1]
    is_valid, result = verify_host_token(token)

    if not is_valid:
        return jsonify({'error': result}), 401

    game = games[pin]
    if result != game['host_id']:
        return jsonify({'error': 'Not authorized to start this game'}), 403

    if game['status'] == 'completed':
        return jsonify({'error': 'Cannot start completed game'}), 400

    game['status'] = 'active'
    socketio.emit('game_started', {'status': 'active'}, room=pin)

    return jsonify({'status': 'started'})

@app.route('/game/<pin>/end', methods=['POST'])
def end_game(pin):
    """End a game session."""
    if pin not in games:
        return jsonify({'error': 'Game not found'}), 404

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token format'}), 401

    token = auth_header.split(' ')[1]
    is_valid, result = verify_host_token(token)

    if not is_valid:
        return jsonify({'error': result}), 401

    game = games[pin]
    if result != game['host_id']:
        return jsonify({'error': 'Not authorized to end this game'}), 403

    game['status'] = 'completed'
    socketio.emit('game_ended', {
        'final_scores': game['scores'],
        'final_streaks': game['streaks']
    }, room=pin)

    return jsonify({'status': 'completed'})

@socketio.on('join_game')
def handle_join_game(data):
    """Handle player joining a game."""
    if not isinstance(data, dict):
        emit('error', {'error': 'Invalid request format'})
        return

    pin = data.get('pin')
    player_name = data.get('name')

    if not pin or not player_name:
        emit('error', {'error': 'Missing required field: name'})
        return

    if pin not in games:
        emit('error', {'error': 'Game not found'})
        return

    game = games[pin]

    if game['status'] == 'completed':
        emit('error', {'error': 'Game is completed'})
        return

    if game['status'] != 'lobby':
        emit('error', {'error': 'Game has already started'})
        return

    if len(game['players']) >= game['max_players']:
        emit('error', {'error': 'Game is full'})
        return

    # Check if player already exists in game
    existing_player = None
    for pid, pdata in game['players'].items():
        if pdata.get('name') == player_name:
            existing_player = pid
            break

    # Use existing player_id or generate new one
    if existing_player:
        player_id = existing_player
    else:
        player_id = f"player_{len(game['players']) + 1}"
        game['players'][player_id] = {
            'id': player_id,
            'name': player_name,
            'joined_at': datetime.now(timezone.utc).isoformat()
        }
        game['scores'][player_id] = 0
        game['streaks'][player_id] = 0

    # Clean up any existing connections for this player
    existing_sids = [
        sid for sid, data in active_players.items()
        if data.get('game_pin') == pin and data.get('player_id') == player_id
    ]
    for sid in existing_sids:
        try:
            leave_room(pin, sid)
            active_players.pop(sid, None)
        except Exception as e:
            print(f"Error cleaning up existing connection: {str(e)}")

    # Add player to room
    join_room(pin)
    active_players[request.sid] = {'game_pin': pin, 'player_id': player_id}

    # Notify all players in the game
    emit('player_joined', {
        'player': game['players'][player_id],
        'player_count': len(game['players'])
    }, room=pin)

@socketio.on('disconnect')
def handle_disconnect():
    """Handle player disconnection."""
    sid = request.sid
    player_data = active_players.get(sid)
    if not player_data:
        return

    pin = player_data.get('game_pin')
    player_id = player_data.get('player_id')
    if not pin or not player_id or pin not in games:
        return

    game = games[pin]
    player = game['players'].get(player_id)
    if not player:
        return

    try:
        # Remove player from game
        player_data = game['players'].pop(player_id, None)
        game['scores'].pop(player_id, None)
        game['streaks'].pop(player_id, None)
        if 'answers' in game:
            game['answers'].pop(player_id, None)

        # Leave the socket room
        leave_room(pin)
        active_players.pop(sid, None)

        # Notify remaining players
        socketio.emit('player_left', {
            'player': player_data,
            'player_count': len(game['players'])
        }, room=pin)
    except Exception as e:
        print(f"Error in disconnect handler: {str(e)}")

@socketio.on('start_game')
def handle_start_game(data):
    """Handle game start by host."""
    pin = data.get('pin')
    token = data.get('token')

    if not pin or not token:
        emit('error', {'error': 'Missing required fields'})
        return

    if pin not in games:
        emit('error', {'error': 'Game not found'})
        return

    is_valid, result = verify_host_token(token)
    if not is_valid:
        emit('error', {'error': result})
        return

    game = games[pin]
    if result != game['host_id']:
        emit('error', {'error': 'Not authorized to start this game'})
        return

    if len(game['players']) < 1:
        emit('error', {'error': 'Not enough players'})
        return

    if game['status'] == 'completed':
        emit('error', {'error': 'Cannot start completed game'})
        return

    game['status'] = 'active'
    emit('game_started', {'status': 'active'}, room=pin)

@socketio.on('start_question')
def handle_start_question(data):
    """Start a new question round."""
    pin = data.get('pin')
    token = data.get('token')
    question_data = data.get('question')

    if not pin or not token or not question_data:
        emit('error', {'error': 'Missing required fields'})
        return

    if pin not in games:
        emit('error', {'error': 'Game not found'})
        return

    game = games[pin]
    is_valid, result = verify_host_token(token)
    if not is_valid:
        emit('error', {'error': result})
        return

    if result != game['host_id']:
        emit('error', {'error': 'Not authorized to start questions'})
        return

    if game['status'] != 'active':
        emit('error', {'error': 'Game not in active state'})
        return

    # Validate question data structure
    required_fields = ['text', 'options', 'correct_answer']
    if not all(field in question_data for field in required_fields):
        emit('error', {'error': 'Invalid question data format'})
        return

    # Cancel any existing question timer
    if pin in question_timers:
        question_timers[pin].kill()

    # Update game state with new question
    game['current_question'] = question_data
    game['question_start_time'] = datetime.now(timezone.utc).timestamp()
    game['round'] += 1
    game['answers'] = {}

    # Emit question to all players in the room
    question_event = {
        'question': question_data['text'],
        'options': question_data['options'],
        'time_limit': QUESTION_TIME_LIMIT,
        'round': game['round']
    }
    emit('question_started', question_event, room=pin)

    # Schedule end of question timer
    def end_question():
        if pin in games and games[pin]['current_question']:
            handle_question_end(pin)
            if pin in question_timers:
                del question_timers[pin]

    question_timers[pin] = spawn_later(QUESTION_TIME_LIMIT + 1, end_question)

@socketio.on('submit_answer')
def handle_submit_answer(data):
    """Handle player answer submission."""
    pin = data.get('pin')
    player_id = data.get('player_id')
    answer = data.get('answer')

    if not all([pin, player_id, answer]):
        emit('error', {'error': 'Missing required fields'})
        return

    if pin not in games:
        emit('error', {'error': 'Game not found'})
        return

    game = games[pin]
    if game['status'] != 'active' or not game['current_question']:
        emit('error', {'error': 'No active question'})
        return

    if player_id not in game['players']:
        emit('error', {'error': 'Player not found'})
        return

    if player_id in game['answers']:
        emit('error', {'error': 'Answer already submitted'})
        return

    if answer not in game['current_question']['options']:
        emit('error', {'error': 'Invalid answer option'})
        return

    current_time = datetime.now(timezone.utc).timestamp()
    time_taken = current_time - game['question_start_time']

    if time_taken > QUESTION_TIME_LIMIT:
        emit('error', {'error': 'Time expired'})
        return

    game['answers'][player_id] = {
        'answer': answer,
        'time_taken': time_taken
    }

    emit('answer_accepted', {
        'time_taken': time_taken
    })

    emit('answer_submitted', {
        'player_id': player_id,
        'player_name': game['players'][player_id]['name']
    }, room=pin)

def handle_question_end(pin, namespace='/'):
    """End question and calculate scores."""
    game = games[pin]
    if not game['current_question']:
        return

    correct_answer = game['current_question']['correct_answer']
    results = {}

    # Calculate scores for each player
    for player_id, player_data in game['answers'].items():
        is_correct = player_data['answer'] == correct_answer
        time_taken = player_data['time_taken']

        # Skip invalid times
        if time_taken <= 0 or time_taken > QUESTION_TIME_LIMIT:
            game['streaks'][player_id] = 0
            continue

        time_bonus = max(0, POINTS_TIME_BONUS * (1 - time_taken / QUESTION_TIME_LIMIT))

        # Update streak and calculate score
        if is_correct:
            game['streaks'][player_id] += 1
            streak_bonus = game['streaks'][player_id] * STREAK_BONUS
            score = POINTS_BASE + int(time_bonus) + streak_bonus
            game['scores'][player_id] += score
        else:
            game['streaks'][player_id] = 0
            score = 0

        results[player_id] = {
            'correct': is_correct,
            'points': score,
            'streak': game['streaks'][player_id]
        }

    # Send results to all players
    socketio.emit('question_ended', {
        'correct_answer': correct_answer,
        'results': results,
        'scores': game['scores'],
        'streaks': game['streaks']
    }, room=pin, namespace=namespace)

    # Reset question state
    game['current_question'] = None
    game['question_start_time'] = None
    game['answers'] = {}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
