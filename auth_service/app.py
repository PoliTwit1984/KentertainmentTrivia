from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
from datetime import datetime, timedelta, UTC
import bcrypt
import os
import secrets
import sys
from pathlib import Path

from shared.cosmosdb import CosmosDB

app = Flask(__name__)
CORS(app)

# Initialize Cosmos DB
db = CosmosDB()

# Configuration
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev_secret_key')
app.config['JWT_EXPIRATION_DELTA'] = timedelta(hours=24)

def generate_host_id():
    """Generate a unique host ID."""
    return f"host_{secrets.token_hex(8)}"

def get_host_data(host_doc):
    """Extract relevant host data from Cosmos DB document."""
    return {
        'id': host_doc['id'],
        'email': host_doc['email'],
        'password_hash': host_doc['password_hash'].encode('utf-8'),
        'created_at': host_doc.get('created_at', datetime.now(UTC).isoformat())
    }

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'service': 'auth',
        'timestamp': datetime.now(UTC).isoformat(),
        'features': {
            'jwt_auth': True,
            'host_management': True,
            'hot_reload': True
        }
    })

@app.route('/host/register', methods=['POST'])
def register_host():
    """Register a new host."""
    data = request.get_json()

    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Missing email or password'}), 400

    email = data['email']
    password = data['password']

    # Check if host exists
    existing_host = db.get_host_by_email(email)
    if existing_host:
        return jsonify({'error': 'Email already registered'}), 409

    # Hash password
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)

    # Create host record
    host_id = generate_host_id()
    host_data = {
        'id': host_id,
        'email': email,
        'password_hash': hashed_password.decode('utf-8'),  # Store as string in Cosmos DB
        'type': 'host',  # For Cosmos DB querying
        'created_at': datetime.now(UTC).isoformat()
    }

    db.create_host(host_data)

    return jsonify({
        'message': 'Host registered successfully',
        'host_id': host_id
    }), 201

@app.route('/host/login', methods=['POST'])
def host_login():
    """Authenticate a host and return a JWT token."""
    data = request.get_json()

    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Missing email or password'}), 400

    email = data['email']
    password = data['password']

    # Get host from Cosmos DB
    host_doc = db.get_host_by_email(email)
    if not host_doc:
        return jsonify({'error': 'Invalid credentials'}), 401

    host = get_host_data(host_doc)

    # Verify password
    if not bcrypt.checkpw(password.encode('utf-8'), host['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401

    # Generate JWT token
    token_payload = {
        'host_id': host['id'],
        'email': email,
        'exp': datetime.now(UTC) + app.config['JWT_EXPIRATION_DELTA']
    }

    token = jwt.encode(
        token_payload,
        app.config['JWT_SECRET_KEY'],
        algorithm='HS256'
    )

    return jsonify({
        'token': token,
        'host_id': host['id']
    })

@app.route('/host/verify', methods=['POST'])
def verify_token():
    """Verify a JWT token."""
    auth_header = request.headers.get('Authorization')

    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid token'}), 401

    token = auth_header.split(' ')[1]

    try:
        payload = jwt.decode(
            token,
            app.config['JWT_SECRET_KEY'],
            algorithms=['HS256']
        )
        return jsonify({
            'valid': True,
            'host_id': payload['host_id']
        })
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Token has expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
