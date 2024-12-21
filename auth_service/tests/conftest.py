import pytest
from unittest.mock import MagicMock
from shared.cosmosdb import CosmosDB

class MockCosmosDB:
    def __init__(self):
        self.hosts = {}  # In-memory storage for testing

    def get_host_by_email(self, email):
        return self.hosts.get(email)

    def create_host(self, host_data):
        self.hosts[host_data['email']] = host_data
        return host_data

@pytest.fixture(autouse=True)
def mock_cosmosdb(monkeypatch):
    """Replace CosmosDB with mock for all tests."""
    mock_db = MockCosmosDB()

    def mock_init(self):
        self.client = MagicMock()
        self.database = MagicMock()
        self.container = MagicMock()

    monkeypatch.setattr(CosmosDB, '__init__', mock_init)
    monkeypatch.setattr(CosmosDB, 'get_host_by_email', mock_db.get_host_by_email)
    monkeypatch.setattr(CosmosDB, 'create_host', mock_db.create_host)

    return mock_db
