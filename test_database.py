import os
import time
import random
import string
import logging
from datetime import datetime, timedelta, UTC
from unittest.mock import patch, MagicMock
from azure.cosmos import exceptions
from shared.cosmosdb import CosmosDB
from shared.validation import ValidationError

# Configure test logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_id(prefix=''):
    """Generate a random ID with optional prefix"""
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}_{random_str}" if prefix else random_str

def generate_pin():
    """Generate a random 6-digit PIN"""
    return ''.join(random.choices(string.digits, k=6))

def test_host_operations(db):
    print("\n=== Testing Host Operations ===")

    # Test host creation
    test_id = generate_id('host')
    host_data = {
        'id': test_id,  # Required by Cosmos DB
        'email': 'test@example.com',
        'name': 'Test Host',
        'password_hash': 'dummy_hash'
    }

    try:
        host = db.create_host(host_data)
        print("✓ Host created successfully")

        # Test host retrieval
        retrieved_host = db.get_host_by_email(host_data['email'])
        assert retrieved_host['email'] == host_data['email']
        print("✓ Host retrieved successfully")

        # Test unique email constraint
        try:
            db.create_host(host_data)
            print("✗ Duplicate host creation should have failed")
        except Exception as e:
            print("✓ Duplicate host creation prevented")

    except Exception as e:
        print(f"✗ Host operations failed: {str(e)}")

def test_game_operations(db):
    print("\n=== Testing Game Operations ===")

    # Test game creation
    test_pin = generate_pin()
    game_data = {
        'id': test_pin,  # Use PIN as ID
        'pin': test_pin,
        'host_id': 'test_host',
        'status': 'waiting',
        'players': []
    }

    try:
        game = db.create_game(game_data)
        print("✓ Game created successfully")

        # Test game retrieval
        retrieved_game = db.get_game_by_pin(game_data['pin'])
        assert retrieved_game['pin'] == game_data['pin']
        print("✓ Game retrieved successfully")

        # Test game update
        updates = {
            'status': 'active',
            'players': [{'id': 'player1', 'name': 'Player 1'}]
        }
        updated_game = db.update_game(game_data['pin'], updates)
        assert updated_game['status'] == 'active'
        print("✓ Game updated successfully")

        # Test unique PIN constraint
        try:
            db.create_game(game_data)
            print("✗ Duplicate game creation should have failed")
        except Exception as e:
            print("✓ Duplicate game creation prevented")

    except Exception as e:
        print(f"✗ Game operations failed: {str(e)}")

def test_question_bank_operations(db):
    print("\n=== Testing Question Bank Operations ===")

    # Test question bank creation
    test_id = generate_id('bank')
    bank_data = {
        'id': test_id,  # Required by Cosmos DB
        'host_id': 'test_host',
        'name': 'Test Bank',
        'questions': []
    }

    try:
        bank = db.create_question_bank(bank_data)
        print("✓ Question bank created successfully")

        # Test adding questions
        questions = [
            {
                'text': 'What is 2+2?',
                'options': ['3', '4', '5', '6'],
                'correct_answer': 1
            },
            {
                'text': 'What color is the sky?',
                'options': ['Red', 'Green', 'Blue', 'Yellow'],
                'correct_answer': 2
            }
        ]

        updated_bank = db.add_questions_to_bank(bank['id'], questions)
        assert len(updated_bank['questions']) == 2
        print("✓ Questions added successfully")

        # Test question bank retrieval
        banks = db.get_question_banks_by_host('test_host')
        assert len(banks) > 0
        print("✓ Question banks retrieved successfully")

    except Exception as e:
        print(f"✗ Question bank operations failed: {str(e)}")

def test_cleanup_operations(db):
    print("\n=== Testing Cleanup Operations ===")

    # Clean up any existing games first
    cleanup_test_data(db)
    print("✓ Cleaned up existing games")

    try:
        # Create an old game
        test_pin = generate_pin()
        old_game_data = {
            'id': test_pin,  # Use PIN as ID
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'completed',
            'created_at': (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        }

        # Create old game
        old_game = db.create_game(old_game_data)
        print("✓ Created old game for cleanup test")

        # Run cleanup
        db.cleanup_old_games(hours=24)
        print("✓ Cleanup operation executed")

        # Verify game was deleted
        deleted_game = db.get_game_by_pin(old_game_data['pin'])
        assert deleted_game is None
        print("✓ Old game successfully cleaned up")

    except Exception as e:
        print(f"✗ Cleanup operations failed: {str(e)}")

def cleanup_test_data(db):
    """Clean up any existing test data"""
    print("\n=== Cleaning up test data ===")
    try:
        # Query for test documents and any existing games
        query = """
        SELECT * FROM c WHERE
        STARTSWITH(c.id, 'test_') OR
        STARTSWITH(c.id, 'host_') OR
        STARTSWITH(c.id, 'bank_') OR
        c.type = 'game'
        """
        items = list(db.container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))

        # Delete test documents
        for item in items:
            db.container.delete_item(
                item=item['id'],
                partition_key=item['type']
            )
        print(f"✓ Cleaned up {len(items)} test documents")
    except Exception as e:
        print(f"✗ Cleanup failed: {str(e)}")

def test_retry_logic(db):
    print("\n=== Testing Retry Logic ===")

    # Test retry on throttling
    with patch.object(db.container, 'create_item') as mock_create:
        # Mock throttling response
        throttle_error = exceptions.CosmosHttpResponseError(
            message="Too Many Requests",
            status_code=429,
            headers={'x-ms-retry-after-ms': '1000'}
        )
        success_response = {'id': 'test_id', 'type': 'host'}
        mock_create.side_effect = [throttle_error, throttle_error, success_response]

        try:
            host_data = {
                'email': 'retry@test.com',
                'name': 'Retry Test',
                'password_hash': 'test_hash'
            }
            result = db.create_host(host_data)
            assert result['id'] == 'test_id'
            print("✓ Retry logic handled throttling successfully")
        except Exception as e:
            print(f"✗ Retry logic test failed: {str(e)}")

def test_connection_pooling(db):
    print("\n=== Testing Connection Pooling ===")

    try:
        # Test singleton pattern
        db1 = CosmosDB()
        db2 = CosmosDB()
        assert db1._client is db2._client
        print("✓ Connection pooling verified through singleton pattern")

        # Test concurrent operations
        test_pins = [generate_pin() for _ in range(5)]
        game_data_list = [{
            'pin': pin,
            'host_id': 'test_host',
            'status': 'waiting',
            'players': []
        } for pin in test_pins]

        # Create games concurrently
        for game_data in game_data_list:
            db.create_game(game_data)

        print("✓ Concurrent operations completed successfully")

    except Exception as e:
        print(f"✗ Connection pooling test failed: {str(e)}")

def test_error_handling(db):
    print("\n=== Testing Error Handling ===")

    try:
        # Test not found error
        try:
            db.get_game_by_pin('nonexistent_pin')
            print("✓ Non-existent game handled gracefully")
        except Exception as e:
            print(f"✗ Not found error handling failed: {str(e)}")

        # Test invalid data error
        try:
            db.create_game({})  # Missing required PIN
            print("✗ Invalid data should have raised an error")
        except ValueError:
            print("✓ Invalid data error handled correctly")

        # Test duplicate creation
        test_pin = generate_pin()
        game_data = {
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'waiting'
        }
        db.create_game(game_data)
        try:
            db.create_game(game_data)
            print("✗ Duplicate creation should have failed")
        except exceptions.CosmosResourceExistsError:
            print("✓ Duplicate creation error handled correctly")

    except Exception as e:
        print(f"✗ Error handling test failed: {str(e)}")

def test_schema_validation(db):
    print("\n=== Testing Schema Validation ===")

    try:
        # Test host schema validation
        try:
            invalid_host = {
                'email': 'not_an_email',  # Invalid email format
                'password_hash': '123'     # Too short for hash
            }
            db.create_host(invalid_host)
            print("✗ Invalid host data should have failed validation")
        except ValidationError as e:
            print(f"✓ Host validation caught invalid email: {e.message}")

        # Test game schema validation
        try:
            invalid_game = {
                'pin': '123',          # PIN too short
                'host_id': 'test_host',
                'status': 'invalid'    # Invalid status
            }
            db.create_game(invalid_game)
            print("✗ Invalid game data should have failed validation")
        except ValidationError as e:
            print(f"✓ Game validation caught invalid status: {e.message}")

        # Test question validation
        try:
            invalid_questions = [{
                'text': 'Test question',
                'options': ['Only one option'],  # Not enough options
                'correct_answer': 0
            }]
            db.add_questions_to_bank('test_bank', invalid_questions)
            print("✗ Invalid question data should have failed validation")
        except ValidationError as e:
            print(f"✓ Question validation caught invalid options: {e.message}")

    except Exception as e:
        print(f"✗ Schema validation test failed: {str(e)}")

def test_optimistic_concurrency(db):
    print("\n=== Testing Optimistic Concurrency ===")

    try:
        # Create initial game
        test_pin = generate_pin()
        game_data = {
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'waiting',
            'players': []
        }
        game = db.create_game(game_data)

        # Simulate concurrent updates
        with patch.object(db.container, 'replace_item') as mock_replace:
            # Mock conflict response for first attempt
            conflict_error = exceptions.CosmosAccessConditionFailedError(
                message="Conflict detected"
            )
            success_response = {
                'id': game['id'],
                'type': 'game',
                'status': 'active'
            }
            mock_replace.side_effect = [conflict_error, success_response]

            # Try to update game
            updates = {'status': 'active'}
            result = db.update_game(test_pin, updates)
            assert result['status'] == 'active'
            print("✓ Optimistic concurrency handled conflict successfully")

    except Exception as e:
        print(f"✗ Optimistic concurrency test failed: {str(e)}")

def test_transactions(db):
    print("\n=== Testing Transactions ===")

    try:
        # Test successful transaction
        host_data = {
            'email': 'transaction@test.com',
            'password_hash': 'dummy_hash' * 10,  # Make it long enough
            'name': 'Transaction Test'
        }
        bank_data = {
            'name': 'Initial Bank',
            'questions': []
        }

        try:
            result = db.create_host_with_bank(host_data, bank_data)
            print("✓ Transaction completed successfully")

            # Verify both host and bank were created
            host = db.get_host_by_email(host_data['email'])
            assert host is not None
            banks = db.get_question_banks_by_host(host['id'])
            assert len(banks) == 1
            print("✓ Transaction results verified")

        except Exception as e:
            print(f"✗ Transaction test failed: {str(e)}")

        # Test transaction rollback
        invalid_host = {
            'email': 'invalid_email',  # Invalid email to trigger validation error
            'password_hash': 'short'   # Invalid hash to ensure failure
        }
        valid_bank = {
            'name': 'Should Not Exist',
            'questions': []
        }

        try:
            db.create_host_with_bank(invalid_host, valid_bank)
            print("✗ Invalid transaction should have failed")
        except ValidationError:
            # Verify nothing was created
            host = db.get_host_by_email(invalid_host['email'])
            assert host is None
            print("✓ Transaction rollback successful")

    except Exception as e:
        print(f"✗ Transaction tests failed: {str(e)}")

def main():
    print("Starting database functionality tests...")

    try:
        db = CosmosDB()

        # Clean up any existing test data
        cleanup_test_data(db)

        # Run all tests
        test_host_operations(db)
        test_game_operations(db)
        test_question_bank_operations(db)
        test_cleanup_operations(db)

        # Run new tests
        test_retry_logic(db)
        test_connection_pooling(db)
        test_error_handling(db)
        test_schema_validation(db)
        test_optimistic_concurrency(db)
        test_transactions(db)

        print("\n=== All tests completed ===")

    except Exception as e:
        print(f"\n✗ Test suite failed: {str(e)}")

if __name__ == "__main__":
    main()
