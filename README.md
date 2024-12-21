# Team Trivia App

A Kahoot-style real-time trivia game designed for team meetings, making them engaging and fun while incorporating company knowledge.

## Architecture

The application follows a microservices architecture with two main services:

1. **Authentication Service** (Port 5001)
   - Host registration and login
   - JWT token management
   - Session validation

2. **Game Service** (Port 5002)
   - Game creation and PIN generation
   - Real-time lobby management
   - Player connection handling via WebSocket

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Virtual environment (venv)

## Setup

1. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies for local development:
```bash
cd auth_service && pip install -r requirements.txt
cd ../game_service && pip install -r requirements.txt
```

3. Build and run services with Docker:
```bash
docker-compose up --build
```

## API Documentation

### Authentication Service

#### Host Registration
```http
POST /host/register
Content-Type: application/json

{
    "email": "host@example.com",
    "password": "secure_password"
}
```

#### Host Login
```http
POST /host/login
Content-Type: application/json

{
    "email": "host@example.com",
    "password": "secure_password"
}
```

### Game Service

#### Create Game
```http
POST /game/create
Authorization: Bearer <host_token>
```

#### Get Game Status
```http
GET /game/<pin>/status
```

### WebSocket Events

#### Join Game
```javascript
socket.emit('join_game', {
    pin: "123456",
    name: "Player Name"
});
```

#### Start Game
```javascript
socket.emit('start_game', {
    pin: "123456",
    token: "host_jwt_token"
});
```

## Testing

Run tests for each service:

```bash
# Auth Service Tests
cd auth_service
pytest tests/

# Game Service Tests
cd game_service
pytest tests/
```

## Development Workflow

1. Make changes to services
2. Run tests to ensure functionality
3. Build and run with Docker to test integration
4. Submit pull request with:
   - Test coverage
   - Documentation updates
   - Change description

## Security Notes

- JWT tokens expire after 24 hours
- Host passwords are hashed with bcrypt
- All endpoints validate authentication
- Rate limiting should be implemented in production
- Secure all environment variables

## Next Steps

1. ✅ Host authentication system
2. ✅ PIN-based game access
3. ✅ Basic lobby system
4. Implement question management
5. Add game flow control
6. Integrate with Azure Cosmos DB
7. Add frontend React application
8. Implement QR code system

## Contributing

1. Create feature branch: `feature/feature-name`
2. Add tests for new functionality
3. Update documentation
4. Submit pull request

## License

[License Type] - See LICENSE file for details
