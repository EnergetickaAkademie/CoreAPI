import jwt
import hashlib
import secrets
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify

# JWT Secret key (in production, this should be an environment variable)
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key-change-in-production')
JWT_ALGORITHM = 'HS256'
TOKEN_EXPIRY_HOURS = 24

class SimpleAuth:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.init_database()
        self.load_users_if_empty()
    
    def init_database(self):
        """Initialize the SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                user_type TEXT NOT NULL,
                group_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def user_exists(self, username):
        """Check if user exists in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def hash_password(self, password, salt=None):
        """Hash password with salt"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        # Combine password and salt, then hash
        password_salt = f"{password}{salt}".encode('utf-8')
        hashed = hashlib.sha256(password_salt).hexdigest()
        
        return hashed, salt
    
    def verify_password(self, password, hashed_password, salt):
        """Verify password against hash"""
        test_hash, _ = self.hash_password(password, salt)
        return test_hash == hashed_password
    
    def create_user(self, username, password, user_type, group_id='group1'):
        """Create a new user"""
        hashed_password, salt = self.hash_password(password)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, salt, user_type, group_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, hashed_password, salt, user_type, group_id))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Username already exists
        finally:
            conn.close()
    
    def authenticate_user(self, username, password):
        """Authenticate user and return user info if valid"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, password_hash, salt, user_type, group_id
            FROM users WHERE username = ?
        ''', (username,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user and self.verify_password(password, user[2], user[3]):
            return {
                'user_id': user[0],
                'username': user[1],
                'user_type': user[4],
                'group_id': user[5] if user[5] else 'group1'
            }
        return None
    
    def generate_token(self, user_info):
        """Generate JWT token for user"""
        payload = {
            'user_id': user_info['user_id'],
            'username': user_info['username'],
            'user_type': user_info['user_type'],
            'group_id': user_info.get('group_id', 'group1'),
            'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
            'iat': datetime.utcnow()
        }
        
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    def get_user_info(self, token):
        """Get user info from JWT token"""
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            'user_id': payload['user_id'],
            'username': payload['username'],
            'user_type': payload['user_type'],
            'group_id': payload.get('group_id', 'group1')
        }
        
    
    def verify_token(self, token):
        """Verify JWT token and return user info"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None  # Token expired
        except jwt.InvalidTokenError:
            return None  # Invalid token
    
    def load_users_if_empty(self):
        """Load default users if database is empty"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        user_count = cursor.fetchone()[0]
        conn.close()
        
        if user_count == 0:
            self.create_default_users()

    def create_default_users(self):
        """Create default users directly"""
        default_users = [
            ('lecturer1', 'lecturer123', 'lecturer', 'group1'),
            ('board1', 'board123', 'board', 'group1'),
            ('board2', 'board456', 'board', 'group1'),
            ('board3', 'board789', 'board', 'group1')
        ]
        
        for username, password, user_type, group_id in default_users:
            success = self.create_user(username, password, user_type, group_id)
            if success:
                print(f"✓ Created default user: {username} ({user_type})")

# Global auth instance
auth = SimpleAuth()

# Helper functions to extract tokens
def get_token_from_request():
    """Extract token from request headers or query parameters"""
    # Try Authorization header first (Bearer token)
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]  # Remove 'Bearer ' prefix
    
    # Try custom header
    token = request.headers.get('X-Auth-Token')
    if token:
        return token
    
    # Try query parameter (for IoT boards)
    token = request.args.get('token')
    if token:
        return token
    
    return None

# Decorators
def require_auth(f):
    """Decorator to require any valid authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        
        if not token:
            return jsonify({'error': 'Authentication token required'}), 401
        
        user_info = auth.verify_token(token)
        if not user_info:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Add user info to request
        request.user = user_info
        return f(*args, **kwargs)
    
    return decorated

def require_lecturer_auth(f):
    """Decorator to require lecturer authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        
        if not token:
            return jsonify({'error': 'Authentication token required'}), 401
        
        user_info = auth.verify_token(token)
        if not user_info:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        if user_info['user_type'] != 'lecturer':
            return jsonify({'error': 'Lecturer access required'}), 403
        
        # Add user info to request
        request.user = user_info
        return f(*args, **kwargs)
    
    return decorated

def require_board_auth(f):
    """Decorator to require board authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        
        if not token:
            return jsonify({'error': 'Authentication token required'}), 401
        
        user_info = auth.verify_token(token)
        if not user_info:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        if user_info['user_type'] != 'board':
            return jsonify({'error': 'Board access required'}), 403
        
        # Add user info to request
        request.user = user_info
        return f(*args, **kwargs)
    
    return decorated

def optional_auth(f):
    """Decorator that allows both authenticated and non-authenticated access"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        
        if token:
            user_info = auth.verify_token(token)
            request.user = user_info if user_info else None
        else:
            request.user = None
        
        return f(*args, **kwargs)
    
    return decorated
