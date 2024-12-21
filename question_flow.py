import requests
import time
import json

# Test configuration
AUTH_SERVICE = 'http://localhost:5001'
QUESTION_SERVICE = 'http://localhost:5003'

def test_host_auth():
    print("\n=== Testing Host Authentication ===")

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

    return login_response.json().get('token')

def test_question_bank_creation(token):
    print("\n=== Testing Question Bank Creation ===")

    # Create a question bank
    print("\n1. Creating question bank...")
    create_bank_response = requests.post(
        f"{QUESTION_SERVICE}/questions/bank",
        headers={'Authorization': f'Bearer {token}'},
        json={
            "name": "Test Question Bank",
            "description": "A test question bank for trivia games"
        }
    )
    print(f"Create Bank Response: {create_bank_response.status_code}")
    print(create_bank_response.json())

    return create_bank_response.json().get('id')

def test_add_custom_question(token, bank_id):
    print("\n=== Testing Custom Question Addition ===")

    # Add a custom question
    question_data = {
        "text": "What is the capital of France?",
        "options": ["Paris", "London", "Berlin", "Madrid"],
        "correct_answer": 0,
        "category": "Geography",
        "difficulty": "easy",
        "source": "custom"
    }

    print("\n1. Adding custom question...")
    add_question_response = requests.post(
        f"{QUESTION_SERVICE}/questions/bank/{bank_id}/questions",
        headers={'Authorization': f'Bearer {token}'},
        json=question_data
    )
    print(f"Add Question Response: {add_question_response.status_code}")
    print(add_question_response.json())

def test_external_apis():
    print("\n=== Testing External API Integration ===")

    # Test OpenTDB API
    print("\n1. Fetching OpenTDB questions...")
    opentdb_response = requests.get(
        f"{QUESTION_SERVICE}/questions/external/opentdb",
        params={'amount': '2'}
    )
    print(f"OpenTDB Response: {opentdb_response.status_code}")
    print(json.dumps(opentdb_response.json(), indent=2))

    # Test Jservice API
    print("\n2. Fetching Jservice questions...")
    jservice_response = requests.get(
        f"{QUESTION_SERVICE}/questions/external/jservice",
        params={'count': '2'}
    )
    print(f"Jservice Response: {jservice_response.status_code}")
    print(json.dumps(jservice_response.json(), indent=2))

def test_game_questions(token):
    print("\n=== Testing Game Questions ===")

    # Get questions for a game
    print("\n1. Getting questions for a game...")
    game_questions_response = requests.get(
        f"{QUESTION_SERVICE}/questions/game/test_game_1",
        headers={'Authorization': f'Bearer {token}'}
    )
    print(f"Game Questions Response: {game_questions_response.status_code}")
    print(json.dumps(game_questions_response.json(), indent=2))

def main():
    print("Waiting for services to start...")
    time.sleep(10)  # Give services time to start

    try:
        # Test host authentication
        token = test_host_auth()

        # Test question bank creation
        bank_id = test_question_bank_creation(token)

        # Test adding a custom question
        test_add_custom_question(token, bank_id)

        # Test external API integration
        test_external_apis()

        # Test getting game questions
        test_game_questions(token)

        print("\n=== All tests completed successfully ===")

    except Exception as e:
        print(f"\nError during testing: {e}")

if __name__ == "__main__":
    main()
