from azure.cosmos import CosmosClient, PartitionKey, exceptions
import os
import random
import string
import logging
import time
from datetime import datetime, UTC
from typing import Dict, List, Optional, Any, Callable, TypeVar, Generic
from functools import wraps
from contextlib import contextmanager
from .validation import (
    validate_schema,
    optimistic_concurrency,
    HostSchema,
    GameSchema,
    QuestionSchema,
    ValidationError
)

T = TypeVar('T')

class TransactionError(Exception):
    """Custom exception for transaction errors."""
    pass

class Transaction(Generic[T]):
    """Class to handle database transactions."""
    def __init__(self, db: 'CosmosDB'):
        self.db = db
        self.operations: List[Callable[[], None]] = []
        self.compensations: List[Callable[[], None]] = []
        self.committed = False

    def add_operation(self, operation: Callable[[], T], compensation: Callable[[], None]) -> None:
        """Add an operation and its compensation to the transaction."""
        self.operations.append(operation)
        self.compensations.append(compensation)

    def commit(self) -> None:
        """Commit all operations in the transaction."""
        try:
            # Execute all operations
            for operation in self.operations:
                operation()
            self.committed = True
            logger.info("Transaction committed successfully")
        except Exception as e:
            logger.error(f"Transaction failed: {str(e)}")
            self.rollback()
            raise TransactionError(f"Transaction failed: {str(e)}")

    def rollback(self) -> None:
        """Rollback all operations in the transaction."""
        if not self.committed:
            # Execute compensations in reverse order
            for compensation in reversed(self.compensations):
                try:
                    compensation()
                except Exception as e:
                    logger.error(f"Rollback operation failed: {str(e)}")
            logger.info("Transaction rolled back")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def retry_on_throttle(max_retries: int = 3, initial_wait: float = 1.0) -> Callable:
    """Decorator to retry operations when requests are throttled."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            wait_time = initial_wait

            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions.CosmosHttpResponseError as e:
                    if e.status_code == 429:  # Too Many Requests
                        if retries == max_retries - 1:
                            logger.error(f"Max retries ({max_retries}) exceeded for operation")
                            raise

                        # Get retry after duration from headers, default to exponential backoff
                        retry_after = float(e.headers.get('x-ms-retry-after-ms',
                                                        wait_time * 1000)) / 1000

                        logger.warning(f"Request throttled. Retrying in {retry_after} seconds...")
                        time.sleep(retry_after)
                        retries += 1
                        wait_time *= 2  # Exponential backoff
                    else:
                        raise
            return func(*args, **kwargs)
        return wrapper
    return decorator

class CosmosDB:
    """Database class with transaction support."""
    _instance = None
    _client = None
    _database = None
    _container = None

    def __new__(cls):
        """Implement singleton pattern for connection pooling."""
        if cls._instance is None:
            cls._instance = super(CosmosDB, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize database connection with transaction support."""
        """Initialize the database connection if not already initialized."""
        if CosmosDB._client is None:
            endpoint = os.environ.get('COSMOS_ENDPOINT')
            key = os.environ.get('COSMOS_KEY')
            if not endpoint or not key:
                raise ValueError("COSMOS_ENDPOINT and COSMOS_KEY environment variables are required")

            # Initialize Cosmos client with connection pooling
            CosmosDB._client = CosmosClient(
                endpoint,
                key,
                connection_policy={
                    'MaxPoolSize': 100,
                    'RequestTimeout': 30  # seconds
                }
            )

            # Get or create database
            CosmosDB._database = CosmosDB._client.create_database_if_not_exists('trivia_db')

            # Single container for all data types
            CosmosDB._container = CosmosDB._database.create_container_if_not_exists(
                id='trivia_data',
                partition_key=PartitionKey(path='/type'),
                unique_key_policy={'uniqueKeys': [
                    {'paths': ['/email']},  # For hosts
                    {'paths': ['/pin']},    # For games
                ]},
                offer_throughput=400  # Single container with 400 RU/s
            )

        self.client = CosmosDB._client
        self.database = CosmosDB._database
        self.container = CosmosDB._container

    def _generate_id(self, prefix: str) -> str:
        """Generate a random ID with a prefix"""
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{prefix}_{random_str}"

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        transaction = Transaction(self)
        try:
            yield transaction
            if not transaction.committed:
                transaction.commit()
        except Exception as e:
            transaction.rollback()
            raise
        finally:
            if not transaction.committed:
                transaction.rollback()

    @retry_on_throttle()
    @validate_schema(HostSchema())
    @optimistic_concurrency
    def create_host(self, host_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new host record."""
        try:
            if 'id' not in host_data:
                host_data['id'] = self._generate_id('host')
            host_data['type'] = 'host'
            host_data['created_at'] = datetime.now(UTC).isoformat()

            logger.info(f"Creating host with ID: {host_data['id']}")
            result = self.container.create_item(body=host_data)
            logger.info(f"Successfully created host: {result['id']}")
            return result

        except exceptions.CosmosResourceExistsError:
            logger.error(f"Host with email {host_data.get('email')} already exists")
            raise
        except Exception as e:
            logger.error(f"Error creating host: {str(e)}")
            raise

    @retry_on_throttle()
    def get_host_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get host by email."""
        try:
            logger.info(f"Fetching host with email: {email}")
            query = "SELECT * FROM c WHERE c.type = 'host' AND c.email = @email"
            params = [{"name": "@email", "value": email}]
            results = list(self.container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            if results:
                logger.info(f"Found host with email: {email}")
            else:
                logger.info(f"No host found with email: {email}")
            return results[0] if results else None

        except Exception as e:
            logger.error(f"Error fetching host by email: {str(e)}")
            raise

    def create_host_with_bank(self, host_data: Dict[str, Any], bank_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a host and their initial question bank in a transaction."""
        with self.transaction() as transaction:
            # Add host creation operation
            def create_host_op():
                return self.create_host(host_data)

            def delete_host_comp():
                try:
                    self.container.delete_item(
                        item=host_data['id'],
                        partition_key='host'
                    )
                except exceptions.CosmosResourceNotFoundError:
                    pass

            transaction.add_operation(create_host_op, delete_host_comp)

            # Add question bank creation operation
            def create_bank_op():
                bank_data['host_id'] = host_data['id']
                return self.create_question_bank(bank_data)

            def delete_bank_comp():
                try:
                    self.container.delete_item(
                        item=bank_data['id'],
                        partition_key='question_bank'
                    )
                except exceptions.CosmosResourceNotFoundError:
                    pass

            transaction.add_operation(create_bank_op, delete_bank_comp)

            # Commit will happen automatically when exiting context
            return host_data

    @retry_on_throttle()
    @validate_schema(GameSchema())
    @optimistic_concurrency
    def create_game(self, game_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new game."""
        try:
            if 'pin' not in game_data:
                raise ValueError("Game data must include a PIN")

            # Use PIN as ID for games
            game_data['id'] = game_data['pin']
            game_data['type'] = 'game'
            game_data['created_at'] = datetime.now(UTC).isoformat()

            logger.info(f"Creating game with PIN: {game_data['pin']}")
            result = self.container.create_item(body=game_data)
            logger.info(f"Successfully created game with PIN: {result['pin']}")
            return result

        except exceptions.CosmosResourceExistsError:
            logger.error(f"Game with PIN {game_data['pin']} already exists")
            raise
        except Exception as e:
            logger.error(f"Error creating game: {str(e)}")
            raise

    @retry_on_throttle()
    def get_game_by_pin(self, pin: str) -> Optional[Dict[str, Any]]:
        """Get game by PIN.

        Args:
            pin: The game's PIN number

        Returns:
            The game document if found, None otherwise

        Note:
            This operation will retry up to 3 times if throttled
        """
        try:
            logger.info(f"Fetching game with PIN: {pin}")
            result = self.container.read_item(
                item=pin,
                partition_key='game'  # type is partition key
            )
            logger.info(f"Found game with PIN: {pin}")
            return result
        except exceptions.CosmosResourceNotFoundError:
            logger.info(f"No game found with PIN: {pin}")
            return None
        except Exception as e:
            logger.error(f"Error fetching game by PIN: {str(e)}")
            return None

    @retry_on_throttle()
    @validate_schema(GameSchema())
    @optimistic_concurrency
    def update_game(self, pin: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update game data with retry logic for throttled requests.

        Args:
            pin: The game's PIN number
            updates: Dictionary of fields to update

        Returns:
            Updated game document

        Raises:
            ValueError: If game not found
            CosmosHttpResponseError: For other Cosmos DB errors
        """
        try:
            logger.info(f"Updating game with PIN: {pin}")
            game = self.get_game_by_pin(pin)
            if not game:
                raise ValueError(f"Game with PIN {pin} not found")

            game.update(updates)
            game['updated_at'] = datetime.now(UTC).isoformat()

            result = self.container.replace_item(
                item=game['id'],
                body=game
            )
            logger.info(f"Successfully updated game: {pin}")
            return result

        except ValueError:
            logger.error(f"Game with PIN {pin} not found")
            raise
        except Exception as e:
            logger.error(f"Error updating game: {str(e)}")
            raise

    @retry_on_throttle()
    @optimistic_concurrency
    def create_question_bank(self, bank_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new question bank with retry logic.

        Args:
            bank_data: Question bank data including host_id and questions

        Returns:
            Created question bank document

        Raises:
            CosmosHttpResponseError: For Cosmos DB errors
        """
        try:
            if 'id' not in bank_data:
                bank_data['id'] = self._generate_id('bank')
            bank_data['type'] = 'question_bank'
            bank_data['created_at'] = datetime.now(UTC).isoformat()

            logger.info(f"Creating question bank with ID: {bank_data['id']}")
            result = self.container.create_item(body=bank_data)
            logger.info(f"Successfully created question bank: {result['id']}")
            return result

        except Exception as e:
            logger.error(f"Error creating question bank: {str(e)}")
            raise

    @retry_on_throttle()
    def get_question_banks_by_host(self, host_id: str) -> List[Dict[str, Any]]:
        """Get all question banks for a host with retry logic.

        Args:
            host_id: ID of the host

        Returns:
            List of question bank documents

        Raises:
            CosmosHttpResponseError: For Cosmos DB errors
        """
        try:
            logger.info(f"Fetching question banks for host: {host_id}")
            query = "SELECT * FROM c WHERE c.type = 'question_bank' AND c.host_id = @host_id"
            params = [{"name": "@host_id", "value": host_id}]
            results = list(self.container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            logger.info(f"Found {len(results)} question banks for host: {host_id}")
            return results

        except Exception as e:
            logger.error(f"Error fetching question banks: {str(e)}")
            raise

    @retry_on_throttle()
    @optimistic_concurrency
    def add_questions_to_bank(self, bank_id: str, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Add questions to a bank with retry logic and validation.

        Args:
            bank_id: ID of the question bank
            questions: List of question documents to add

        Returns:
            Updated question bank document

        Raises:
            ValidationError: If questions don't match schema
            CosmosResourceNotFoundError: If bank not found
            CosmosHttpResponseError: For other Cosmos DB errors
        """
        # Validate each question against schema
        question_schema = QuestionSchema()
        for question in questions:
            question_schema.validate(question)
        """Add questions to a bank with retry logic.

        Args:
            bank_id: ID of the question bank
            questions: List of question documents to add

        Returns:
            Updated question bank document

        Raises:
            CosmosResourceNotFoundError: If bank not found
            CosmosHttpResponseError: For other Cosmos DB errors
        """
        try:
            logger.info(f"Adding questions to bank: {bank_id}")
            bank = self.container.read_item(
                item=bank_id,
                partition_key='question_bank'  # type is partition key
            )

            if 'questions' not in bank:
                bank['questions'] = []

            bank['questions'].extend(questions)
            bank['updated_at'] = datetime.now(UTC).isoformat()

            result = self.container.replace_item(
                item=bank['id'],
                body=bank
            )
            logger.info(f"Successfully added {len(questions)} questions to bank: {bank_id}")
            return result

        except exceptions.CosmosResourceNotFoundError:
            logger.error(f"Question bank {bank_id} not found")
            raise
        except Exception as e:
            logger.error(f"Error adding questions to bank: {str(e)}")
            raise

    @retry_on_throttle()
    def delete_game(self, pin: str) -> None:
        """Delete a game with retry logic.

        Args:
            pin: The game's PIN number

        Raises:
            CosmosResourceNotFoundError: If game not found
            CosmosHttpResponseError: For other Cosmos DB errors
        """
        try:
            logger.info(f"Deleting game with PIN: {pin}")
            self.container.delete_item(
                item=pin,
                partition_key='game'  # type is partition key
            )
            logger.info(f"Successfully deleted game: {pin}")

        except exceptions.CosmosResourceNotFoundError:
            logger.warning(f"Game with PIN {pin} not found for deletion")
        except Exception as e:
            logger.error(f"Error deleting game: {str(e)}")
            raise

    @retry_on_throttle()
    def cleanup_old_games(self, hours: int = 24) -> None:
        """Clean up games older than specified hours with retry logic.

        Args:
            hours: Number of hours after which games are considered old

        Note:
            This operation will retry individual game deletions if throttled
        """
        try:
            logger.info(f"Starting cleanup of games older than {hours} hours")
            cutoff = datetime.now(UTC).isoformat()
            query = f"SELECT * FROM c WHERE c.type = 'game' AND c.created_at < '{cutoff}'"

            old_games = list(self.container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))

            logger.info(f"Found {len(old_games)} old games to clean up")
            for game in old_games:
                try:
                    self.delete_game(game['pin'])
                except Exception as e:
                    logger.error(f"Error deleting game {game['pin']} during cleanup: {str(e)}")

            logger.info("Game cleanup completed")

        except Exception as e:
            logger.error(f"Error during game cleanup: {str(e)}")
            raise
