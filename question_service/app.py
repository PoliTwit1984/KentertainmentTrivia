from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

app = Flask(__name__)
CORS(app)

# In-memory storage for development (replace with Cosmos DB in production)
question_banks: Dict[str, List[dict]] = {}
questions_cache: Dict[str, dict] = {}

# External API configurations
OPENTDB_API_URL = "https://opentdb.com/api.php"
JSERVICE_API_URL = "https://jservice.io/api"

# Models for validation
class Question(BaseModel):
    text: str
    options: List[str]
    correct_answer: int
    category: str
    difficulty: str
    source: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class QuestionBank(BaseModel):
    id: str
    name: str
    description: str
    questions: List[Question]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

def verify_host_token(token: str) -> tuple[bool, Optional[str]]:
    """Verify host token with auth service."""
    auth_service_url = os.environ.get('AUTH_SERVICE_URL', 'http://localhost:5001')
    try:
        response = requests.post(
            f"{auth_service_url}/host/verify",
            headers={'Authorization': f'Bearer {token}'}
        )
        return response.status_code == 200, response.json().get('host_id')
    except requests.RequestException:
        return False, None

def format_opentdb_question(raw_question: dict) -> dict:
    """Format OpenTDB question to our standard format."""
    options = [raw_question['correct_answer']] + raw_question['incorrect_answers']
    correct_index = 0  # Since we added correct answer first

    # Shuffle options and track new correct index
    import random
    shuffled = list(enumerate(options))
    random.shuffle(shuffled)
    indices, options = zip(*shuffled)
    correct_index = indices.index(0)

    return {
        'text': raw_question['question'],
        'options': list(options),
        'correct_answer': correct_index,
        'category': raw_question['category'],
        'difficulty': raw_question['difficulty'],
        'source': 'opentdb'
    }

def format_jservice_question(raw_question: dict) -> dict:
    """Format Jservice question to our standard format."""
    import html
    import random

    # Clean up text and answer
    question_text = html.unescape(raw_question['question'])
    correct_answer = html.unescape(raw_question['answer'])

    # Generate plausible wrong answers (in production, these would be more sophisticated)
    wrong_answers = [
        f"Option {i}" for i in range(3)  # Generate 3 dummy options
    ]

    # Combine and shuffle options
    options = [correct_answer] + wrong_answers
    random.shuffle(options)
    correct_index = options.index(correct_answer)

    return {
        'text': question_text,
        'options': options,
        'correct_answer': correct_index,
        'category': raw_question['category']['title'],
        'difficulty': 'medium',  # Jservice doesn't provide difficulty
        'source': 'jservice'
    }

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'service': 'question',
        'timestamp': datetime.utcnow().isoformat(),
        'features': {
            'question_banks': True,
            'external_apis': True,
            'hot_reload': True
        }
    })

@app.route('/questions/bank', methods=['POST'])
def create_question_bank():
    """Create a new question bank."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]
    is_valid, host_id = verify_host_token(token)
    if not is_valid:
        return jsonify({'error': 'Invalid host token'}), 401

    data = request.json
    if not data or 'name' not in data:
        return jsonify({'error': 'Missing required fields'}), 400

    bank_id = f"bank_{len(question_banks) + 1}"
    question_banks[bank_id] = {
        'id': bank_id,
        'name': data['name'],
        'description': data.get('description', ''),
        'questions': [],
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }

    return jsonify({
        'id': bank_id,
        'status': 'created'
    })

@app.route('/questions/bank/<bank_id>', methods=['GET'])
def get_question_bank(bank_id):
    """Get a question bank by ID."""
    if bank_id not in question_banks:
        return jsonify({'error': 'Question bank not found'}), 404

    return jsonify(question_banks[bank_id])

@app.route('/questions/bank/<bank_id>/questions', methods=['POST'])
def add_question(bank_id):
    """Add a question to a bank."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]
    is_valid, host_id = verify_host_token(token)
    if not is_valid:
        return jsonify({'error': 'Invalid host token'}), 401

    if bank_id not in question_banks:
        return jsonify({'error': 'Question bank not found'}), 404

    data = request.json
    try:
        question = Question(**data)
        question_banks[bank_id]['questions'].append(question.dict())
        question_banks[bank_id]['updated_at'] = datetime.utcnow().isoformat()
        return jsonify({'status': 'added'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/questions/external/opentdb', methods=['GET'])
def get_opentdb_questions():
    """Fetch questions from OpenTDB API."""
    try:
        amount = request.args.get('amount', '10')
        category = request.args.get('category', '')
        difficulty = request.args.get('difficulty', '')

        params = {'amount': amount}
        if category:
            params['category'] = category
        if difficulty:
            params['difficulty'] = difficulty

        response = requests.get(OPENTDB_API_URL, params=params)
        if response.status_code != 200:
            return jsonify({'error': 'Failed to fetch questions'}), 500

        data = response.json()
        formatted_questions = [
            format_opentdb_question(q) for q in data['results']
        ]
        return jsonify(formatted_questions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/questions/external/jservice', methods=['GET'])
def get_jservice_questions():
    """Fetch questions from Jservice API."""
    try:
        count = request.args.get('count', '10')
        # Add timeout to prevent hanging
        response = requests.get(
            f"{JSERVICE_API_URL}/random",
            params={'count': count},
            timeout=5,
            verify=False  # Skip SSL verification for development
        )

        if response.status_code != 200:
            # Fallback to custom questions if API fails
            fallback_questions = [
                {
                    'text': 'What is the capital of France?',
                    'options': ['Paris', 'London', 'Berlin', 'Madrid'],
                    'correct_answer': 0,
                    'category': 'Geography',
                    'difficulty': 'easy',
                    'source': 'custom'
                },
                {
                    'text': 'Which planet is known as the Red Planet?',
                    'options': ['Mars', 'Venus', 'Jupiter', 'Saturn'],
                    'correct_answer': 0,
                    'category': 'Science',
                    'difficulty': 'easy',
                    'source': 'custom'
                }
            ]
            return jsonify(fallback_questions)

        questions = response.json()
        if not isinstance(questions, list) or not questions:
            return jsonify(fallback_questions)

        formatted_questions = [
            format_jservice_question(q) for q in questions
        ]
        return jsonify(formatted_questions)
    except Exception as e:
        app.logger.error(f"Jservice API error: {str(e)}")
        # Return fallback questions on error
        return jsonify([
            {
                'text': 'What is the capital of France?',
                'options': ['Paris', 'London', 'Berlin', 'Madrid'],
                'correct_answer': 0,
                'category': 'Geography',
                'difficulty': 'easy',
                'source': 'custom'
            },
            {
                'text': 'Which planet is known as the Red Planet?',
                'options': ['Mars', 'Venus', 'Jupiter', 'Saturn'],
                'correct_answer': 0,
                'category': 'Science',
                'difficulty': 'easy',
                'source': 'custom'
            }
        ])

@app.route('/questions/game/<game_id>', methods=['GET'])
def get_game_questions(game_id):
    """Get questions for a specific game."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]
    is_valid, host_id = verify_host_token(token)
    if not is_valid:
        return jsonify({'error': 'Invalid host token'}), 401

    # Check if we have cached questions
    if game_id in questions_cache:
        return jsonify(questions_cache[game_id])

    # For now, return a mix of questions from different sources
    # In production, this would be based on game settings and question banks
    try:
        questions = []

        # Try to get OpenTDB questions
        try:
            opentdb_response = requests.get(
                OPENTDB_API_URL,
                params={'amount': '5'},
                timeout=5
            )
            if opentdb_response.status_code == 200:
                opentdb_data = opentdb_response.json()
                if opentdb_data.get('response_code') == 0:
                    questions.extend([
                        format_opentdb_question(q)
                        for q in opentdb_data['results']
                    ])
        except Exception as e:
            app.logger.error(f"OpenTDB API error: {str(e)}")

        # Try to get Jservice questions
        try:
            jservice_response = requests.get(
                f"{JSERVICE_API_URL}/random",
                params={'count': '5'},
                timeout=5,
                verify=False
            )
            if jservice_response.status_code == 200:
                jservice_data = jservice_response.json()
                if isinstance(jservice_data, list):
                    questions.extend([
                        format_jservice_question(q)
                        for q in jservice_data
                    ])
        except Exception as e:
            app.logger.error(f"Jservice API error: {str(e)}")

        # Always ensure we have enough questions by adding custom ones
        custom_questions = [
            {
                'text': 'What is the capital of France?',
                'options': ['Paris', 'London', 'Berlin', 'Madrid'],
                'correct_answer': 0,
                'category': 'Geography',
                'difficulty': 'easy',
                'source': 'custom'
            },
            {
                'text': 'Which planet is known as the Red Planet?',
                'options': ['Mars', 'Venus', 'Jupiter', 'Saturn'],
                'correct_answer': 0,
                'category': 'Science',
                'difficulty': 'easy',
                'source': 'custom'
            },
            {
                'text': 'What is the largest mammal in the world?',
                'options': ['Blue Whale', 'African Elephant', 'Giraffe', 'Polar Bear'],
                'correct_answer': 0,
                'category': 'Science',
                'difficulty': 'easy',
                'source': 'custom'
            },
            {
                'text': 'Which programming language was created by Guido van Rossum?',
                'options': ['Python', 'Java', 'C++', 'JavaScript'],
                'correct_answer': 0,
                'category': 'Technology',
                'difficulty': 'easy',
                'source': 'custom'
            },
            {
                'text': 'What is the chemical symbol for gold?',
                'options': ['Au', 'Ag', 'Fe', 'Cu'],
                'correct_answer': 0,
                'category': 'Science',
                'difficulty': 'easy',
                'source': 'custom'
            }
        ]

        # Add custom questions if we don't have enough
        if len(questions) < 5:
            questions.extend(custom_questions[:5 - len(questions)])

        # Cache questions for this game
        questions_cache[game_id] = questions
        return jsonify(questions)
    except Exception as e:
        app.logger.error(f"Game questions error: {str(e)}")
        # Return custom questions as fallback
        return jsonify(custom_questions)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port)
