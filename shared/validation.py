"""Data validation and middleware for the trivia application."""
from functools import wraps
from typing import Dict, Any, Callable, Type, Optional, List, Union
from datetime import datetime
import re
from azure.cosmos import exceptions

class ValidationError(Exception):
    """Custom exception for validation errors."""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(self.message)

class Schema:
    """Base schema class for data validation."""
    def __init__(self, **kwargs):
        self.required: List[str] = kwargs.get('required', [])
        self.optional: List[str] = kwargs.get('optional', [])
        self.field_types: Dict[str, Type] = kwargs.get('field_types', {})
        self.validators: Dict[str, List[Callable]] = kwargs.get('validators', {})

    def validate(self, data: Dict[str, Any]) -> None:
        """Validate data against schema."""
        # Check required fields
        for field in self.required:
            if field not in data:
                raise ValidationError(f"Missing required field: {field}", field)

        # Check field types
        for field, value in data.items():
            if field in self.field_types:
                expected_type = self.field_types[field]
                if not isinstance(value, expected_type):
                    raise ValidationError(
                        f"Invalid type for {field}. Expected {expected_type.__name__}, got {type(value).__name__}",
                        field
                    )

        # Run field validators
        for field, validators in self.validators.items():
            if field in data:
                for validator in validators:
                    try:
                        validator(data[field])
                    except Exception as e:
                        raise ValidationError(str(e), field)

class HostSchema(Schema):
    """Schema for host data."""
    def __init__(self):
        super().__init__(
            required=['email', 'password_hash'],
            optional=['name'],
            field_types={
                'email': str,
                'password_hash': str,
                'name': str
            },
            validators={
                'email': [self._validate_email],
                'password_hash': [self._validate_password_hash]
            }
        )

    def _validate_email(self, email: str) -> None:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            raise ValidationError("Invalid email format")

    def _validate_password_hash(self, hash_value: str) -> None:
        """Validate password hash format."""
        if len(hash_value) < 60:  # Assuming bcrypt hash length
            raise ValidationError("Invalid password hash format")

class GameSchema(Schema):
    """Schema for game data."""
    def __init__(self):
        super().__init__(
            required=['pin', 'host_id', 'status'],
            optional=['players', 'current_question', 'scores'],
            field_types={
                'pin': str,
                'host_id': str,
                'status': str,
                'players': list,
                'current_question': dict,
                'scores': dict
            },
            validators={
                'pin': [self._validate_pin],
                'status': [self._validate_status],
                'players': [self._validate_players]
            }
        )

    def _validate_pin(self, pin: str) -> None:
        """Validate game PIN format."""
        if not re.match(r'^\d{6}$', pin):
            raise ValidationError("PIN must be 6 digits")

    def _validate_status(self, status: str) -> None:
        """Validate game status."""
        valid_statuses = {'waiting', 'active', 'question', 'completed'}
        if status not in valid_statuses:
            raise ValidationError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")

    def _validate_players(self, players: List[Dict[str, Any]]) -> None:
        """Validate player data."""
        for player in players:
            if not isinstance(player, dict):
                raise ValidationError("Invalid player data format")
            if 'id' not in player or 'name' not in player:
                raise ValidationError("Player must have id and name")

class QuestionSchema(Schema):
    """Schema for question data."""
    def __init__(self):
        super().__init__(
            required=['text', 'options', 'correct_answer'],
            optional=['category', 'difficulty', 'source'],
            field_types={
                'text': str,
                'options': list,
                'correct_answer': int,
                'category': str,
                'difficulty': str,
                'source': str
            },
            validators={
                'options': [self._validate_options],
                'correct_answer': [self._validate_correct_answer],
                'difficulty': [self._validate_difficulty]
            }
        )

    def _validate_options(self, options: List[str]) -> None:
        """Validate question options."""
        if not (2 <= len(options) <= 4):
            raise ValidationError("Must have 2-4 options")
        if not all(isinstance(opt, str) for opt in options):
            raise ValidationError("All options must be strings")

    def _validate_correct_answer(self, answer: int) -> None:
        """Validate correct answer index."""
        if not isinstance(answer, int) or answer < 0:
            raise ValidationError("Correct answer must be a non-negative integer")

    def _validate_difficulty(self, difficulty: str) -> None:
        """Validate question difficulty."""
        valid_difficulties = {'easy', 'medium', 'hard'}
        if difficulty not in valid_difficulties:
            raise ValidationError(f"Invalid difficulty. Must be one of: {', '.join(valid_difficulties)}")

def validate_schema(schema: Schema) -> Callable:
    """Decorator to validate data against a schema."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract data from args/kwargs based on function signature
            data = args[1] if len(args) > 1 else kwargs.get('data')
            if not data:
                raise ValidationError("No data provided for validation")

            # Validate data against schema
            schema.validate(data)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def optimistic_concurrency(func: Callable) -> Callable:
    """Decorator to implement optimistic concurrency control."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Get current version of document (if it exists)
                if hasattr(args[0], 'container'):
                    db = args[0]
                    data = args[1] if len(args) > 1 else kwargs.get('data')

                    if 'id' in data:
                        try:
                            existing = db.container.read_item(
                                item=data['id'],
                                partition_key=data.get('type', 'default')
                            )
                            # Update with current ETag
                            data['_etag'] = existing['_etag']
                        except exceptions.CosmosResourceNotFoundError:
                            pass  # New document, no ETag needed

                result = func(*args, **kwargs)
                return result

            except exceptions.CosmosAccessConditionFailedError:
                retry_count += 1
                if retry_count == max_retries:
                    raise ValidationError("Concurrent update detected. Please try again.")
                continue

            except Exception as e:
                raise e

    return wrapper
