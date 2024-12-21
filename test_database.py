"""Test database operations and functionality."""
import pytest
import asyncio
import random
import string
from datetime import datetime, timedelta, UTC
from unittest.mock import patch, AsyncMock
from azure.cosmos import exceptions
from shared.cosmosdb import CosmosDB
from shared.validation import ValidationError

# Constants for test configuration
TEST_TIMEOUT = 5  # seconds
MAX_RETRIES = 3
CLEANUP_HOURS = 24


def generate_id(prefix=''):
    """Generate a random ID with optional prefix."""
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}_{random_str}" if prefix else random_str


def generate_pin():
    """Generate a random 6-digit PIN."""
    return ''.join(random.choices(string.digits, k=6))


@pytest.fixture(scope="function", autouse=True)
async def setup_and_teardown():
    """Setup and teardown for each test."""
    # Setup
    db = CosmosDB()
    await cleanup_test_data(db)

    yield db

    # Teardown
    await asyncio.sleep(0.1)  # Allow any pending events to complete
    await cleanup_test_data(db)


async def cleanup_test_data(db):
    """Clean up any existing test data."""
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
            await db.container.delete_item(
                item=item['id'],
                partition_key=item['type']
            )
    except Exception as e:
        pytest.fail(f"Cleanup failed: {str(e)}")


@pytest.mark.asyncio
async def test_host_operations(setup_and_teardown):
    """Test host operations."""
    db = setup_and_teardown
    try:
        # Test host creation
        test_id = generate_id('host')
        host_data = {
            'id': test_id,
            'email': 'test@example.com',
            'name': 'Test Host',
            'password_hash': 'dummy_hash'
        }

        # Create host
        host = await db.create_host(host_data)
        assert host['id'] == test_id

        # Test host retrieval
        retrieved_host = await db.get_host_by_email(host_data['email'])
        assert retrieved_host['email'] == host_data['email']

        # Test unique email constraint
        with pytest.raises(exceptions.CosmosResourceExistsError):
            await db.create_host(host_data)

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_game_operations(setup_and_teardown):
    """Test game operations."""
    db = setup_and_teardown
    try:
        # Test game creation
        test_pin = generate_pin()
        game_data = {
            'id': test_pin,
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'waiting',
            'players': []
        }

        # Create game
        game = await db.create_game(game_data)
        assert game['pin'] == test_pin

        # Test game retrieval
        retrieved_game = await db.get_game_by_pin(game_data['pin'])
        assert retrieved_game['pin'] == game_data['pin']

        # Test game update
        updates = {
            'status': 'active',
            'players': [{'id': 'player1', 'name': 'Player 1'}]
        }
        updated_game = await db.update_game(game_data['pin'], updates)
        assert updated_game['status'] == 'active'

        # Test unique PIN constraint
        with pytest.raises(exceptions.CosmosResourceExistsError):
            await db.create_game(game_data)

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_question_bank_operations(setup_and_teardown):
    """Test question bank operations."""
    db = setup_and_teardown
    try:
        # Test question bank creation
        test_id = generate_id('bank')
        bank_data = {
            'id': test_id,
            'host_id': 'test_host',
            'name': 'Test Bank',
            'questions': []
        }

        # Create bank
        bank = await db.create_question_bank(bank_data)
        assert bank['id'] == test_id

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

        updated_bank = await db.add_questions_to_bank(bank['id'], questions)
        assert len(updated_bank['questions']) == 2

        # Test question bank retrieval
        banks = await db.get_question_banks_by_host('test_host')
        assert len(banks) > 0

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_cleanup_operations(setup_and_teardown):
    """Test cleanup operations."""
    db = setup_and_teardown
    try:
        # Create an old game
        test_pin = generate_pin()
        old_game_data = {
            'id': test_pin,
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'completed',
            'created_at': (datetime.now(UTC) - timedelta(hours=CLEANUP_HOURS + 1)).isoformat()
        }

        # Create old game
        old_game = await db.create_game(old_game_data)
        assert old_game['pin'] == test_pin

        # Run cleanup
        await db.cleanup_old_games(hours=CLEANUP_HOURS)

        # Verify game was deleted
        deleted_game = await db.get_game_by_pin(old_game_data['pin'])
        assert deleted_game is None

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_retry_logic(setup_and_teardown):
    """Test retry logic for throttled operations."""
    db = setup_and_teardown
    try:
        with patch.object(db.container, 'create_item') as mock_create:
            # Mock throttling response
            throttle_error = exceptions.CosmosHttpResponseError(
                message="Too Many Requests",
                status_code=429,
                headers={'x-ms-retry-after-ms': '1000'}
            )
            success_response = {'id': 'test_id', 'type': 'host'}
            mock_create.side_effect = [throttle_error, throttle_error, success_response]

            host_data = {
                'email': 'retry@test.com',
                'name': 'Retry Test',
                'password_hash': 'test_hash'
            }
            result = await db.create_host(host_data)
            assert result['id'] == 'test_id'

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_connection_pooling(setup_and_teardown):
    """Test connection pooling and concurrent operations."""
    db = setup_and_teardown
    try:
        # Test singleton pattern
        db1 = CosmosDB()
        db2 = CosmosDB()
        assert db1._client is db2._client

        # Test concurrent operations
        test_pins = [generate_pin() for _ in range(5)]
        game_data_list = [{
            'pin': pin,
            'host_id': 'test_host',
            'status': 'waiting',
            'players': []
        } for pin in test_pins]

        # Create games concurrently
        tasks = [db.create_game(game_data) for game_data in game_data_list]
        await asyncio.gather(*tasks)

        # Verify all games were created
        for pin in test_pins:
            game = await db.get_game_by_pin(pin)
            assert game is not None

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_error_handling(setup_and_teardown):
    """Test error handling scenarios."""
    db = setup_and_teardown
    try:
        # Test not found error
        nonexistent_game = await db.get_game_by_pin('nonexistent_pin')
        assert nonexistent_game is None

        # Test invalid data error
        with pytest.raises(ValueError):
            await db.create_game({})  # Missing required PIN

        # Test duplicate creation
        test_pin = generate_pin()
        game_data = {
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'waiting'
        }
        await db.create_game(game_data)
        with pytest.raises(exceptions.CosmosResourceExistsError):
            await db.create_game(game_data)

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_schema_validation(setup_and_teardown):
    """Test schema validation."""
    db = setup_and_teardown
    try:
        # Test host schema validation
        with pytest.raises(ValidationError):
            invalid_host = {
                'email': 'not_an_email',  # Invalid email format
                'password_hash': '123'     # Too short for hash
            }
            await db.create_host(invalid_host)

        # Test game schema validation
        with pytest.raises(ValidationError):
            invalid_game = {
                'pin': '123',          # PIN too short
                'host_id': 'test_host',
                'status': 'invalid'    # Invalid status
            }
            await db.create_game(invalid_game)

        # Test question validation
        with pytest.raises(ValidationError):
            invalid_questions = [{
                'text': 'Test question',
                'options': ['Only one option'],  # Not enough options
                'correct_answer': 0
            }]
            await db.add_questions_to_bank('test_bank', invalid_questions)

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_optimistic_concurrency(setup_and_teardown):
    """Test optimistic concurrency control."""
    db = setup_and_teardown
    try:
        # Create initial game
        test_pin = generate_pin()
        game_data = {
            'pin': test_pin,
            'host_id': 'test_host',
            'status': 'waiting',
            'players': []
        }
        game = await db.create_game(game_data)

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
            result = await db.update_game(test_pin, updates)
            assert result['status'] == 'active'

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")


@pytest.mark.asyncio
async def test_transactions(setup_and_teardown):
    """Test transaction support."""
    db = setup_and_teardown
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

        result = await db.create_host_with_bank(host_data, bank_data)
        assert result is not None

        # Verify both host and bank were created
        host = await db.get_host_by_email(host_data['email'])
        assert host is not None
        banks = await db.get_question_banks_by_host(host['id'])
        assert len(banks) == 1

        # Test transaction rollback
        invalid_host = {
            'email': 'invalid_email',  # Invalid email to trigger validation error
            'password_hash': 'short'   # Invalid hash to ensure failure
        }
        valid_bank = {
            'name': 'Should Not Exist',
            'questions': []
        }

        with pytest.raises(ValidationError):
            await db.create_host_with_bank(invalid_host, valid_bank)

        # Verify nothing was created
        host = await db.get_host_by_email(invalid_host['email'])
        assert host is None

    except Exception as e:
        pytest.fail(f"Test failed: {str(e)}")
