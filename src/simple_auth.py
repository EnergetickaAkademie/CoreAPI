import jwt
import hashlib
import secrets
import sqlite3
import csv
import os
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from config_loader import config_loader

# JWT Secret key (in production, this should be an environment variable)
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key-change-in-production')
JWT_ALGORITHM = 'HS256'
TOKEN_EXPIRY_HOURS = 24

class SimpleAuth:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.init_database()
        self.load_users_from_config()
    
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
                name TEXT NOT NULL,
                metadata TEXT,
                group_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def load_users_from_config(self):
        """Load users from TOML configuration"""
        try:
            users = config_loader.get_all_users()
            for username, user_info in users.items():
                # Check if user already exists
                if not self.user_exists(username):
                    # Add group_id to metadata
                    metadata = user_info.get('metadata', {})
                    group_id = metadata.get('group_id', 'group1')  # Default to group1
                    
                    self.create_user(
                        username=username,
                        password=user_info['password'],
                        user_type=user_info['user_type'],
                        name=user_info['name'],
                        metadata=json.dumps(metadata),
                        group_id=group_id
                    )
            print(f"✅ Loaded {len(users)} users from configuration")
        except Exception as e:
            print(f"⚠️ Failed to load users from config: {e}")
            # Fallback to loading default users
            self.load_users_if_empty()
    
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
    
    def create_user(self, username, password, user_type, name, metadata=None, group_id='group1'):
        """Create a new user"""
        hashed_password, salt = self.hash_password(password)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO users (username, password_hash, salt, user_type, name, metadata, group_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (username, hashed_password, salt, user_type, name, metadata, group_id))
            
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
            SELECT id, username, password_hash, salt, user_type, name, metadata, group_id
            FROM users WHERE username = ?
        ''', (username,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user and self.verify_password(password, user[2], user[3]):
            return {
                'user_id': user[0],  # Changed from 'id' to 'user_id' for JWT compatibility
                'username': user[1],
                'user_type': user[4],
                'name': user[5],
                'metadata': user[6],
                'group_id': user[7] if user[7] else 'group1'  # Default to group1 if None
            }
        return None
    
    def generate_token(self, user_info):
        """Generate JWT token for user"""
        payload = {
            'user_id': user_info['user_id'],  # Changed from 'id' to 'user_id'
            'username': user_info['username'],
            'user_type': user_info['user_type'],
            'name': user_info['name'],
            'metadata': user_info['metadata'],
            'group_id': user_info.get('group_id', 'group1'),  # Include group_id in token
            'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
            'iat': datetime.utcnow()
        }
        
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
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
        """Load users from CSV file if database is empty"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        user_count = cursor.fetchone()[0]
        conn.close()
        
        if user_count == 0:
            self.load_users_from_csv()
    
    def load_users_from_csv(self):
        """Load users from CSV file"""
        csv_file = 'users.csv'
        
        # Create default CSV file if it doesn't exist
        if not os.path.exists(csv_file):
            self.create_default_csv(csv_file)
        
        try:
            with open(csv_file, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    username = row['username']
                    password = row['password']
                    user_type = row['user_type']
                    name = row['name']
                    metadata = row.get('metadata', '')
                    
                    success = self.create_user(username, password, user_type, name, metadata)
                    if success:
                        print(f"✓ Created user: {username} ({user_type})")
                    else:
                        print(f"✗ Failed to create user: {username} (already exists)")
        
        except FileNotFoundError:
            print("CSV file not found, creating default users...")
            self.create_default_users()
        except Exception as e:
            print(f"Error loading users from CSV: {e}")
            self.create_default_users()
    
    def create_default_csv(self, csv_file):
        """Create a default CSV file with sample users"""
        default_users = [
            {
                'username': 'lecturer1',
                'password': 'lecturer123',
                'user_type': 'lecturer',
                'name': 'Dr. John Smith',
                'metadata': '{"department": "Computer Science"}'
            },
            {
                'username': 'lecturer2',
                'password': 'lecturer456',
                'user_type': 'lecturer',
                'name': 'Prof. Maria Garcia',
                'metadata': '{"department": "Physics"}'
            },
            {
                'username': 'board1',
                'password': 'board123',
                'user_type': 'board',
                'name': 'Solar Panel Board #1',
                'metadata': '{"board_type": "solar", "location": "Building A"}'
            },
            {
                'username': 'board2',
                'password': 'board456',
                'user_type': 'board',
                'name': 'Wind Turbine Board #2',
                'metadata': '{"board_type": "wind", "location": "Building B"}'
            },
            {
                'username': 'board3',
                'password': 'board789',
                'user_type': 'board',
                'name': 'Battery Storage Board #3',
                'metadata': '{"board_type": "storage", "location": "Building C"}'
            }
        ]
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as file:
            fieldnames = ['username', 'password', 'user_type', 'name', 'metadata']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            
            writer.writeheader()
            for user in default_users:
                writer.writerow(user)
        
        print(f"Created default CSV file: {csv_file}")
    
    def create_default_users(self):
        """Create default users directly"""
        default_users = [
            ('lecturer1', 'lecturer123', 'lecturer', 'Dr. John Smith', '{"department": "Computer Science"}'),
            ('lecturer2', 'lecturer456', 'lecturer', 'Prof. Maria Garcia', '{"department": "Physics"}'),
            ('board1', 'board123', 'board', 'Solar Panel Board #1', '{"board_type": "solar", "location": "Building A"}'),
            ('board2', 'board456', 'board', 'Wind Turbine Board #2', '{"board_type": "wind", "location": "Building B"}'),
            ('board3', 'board789', 'board', 'Battery Storage Board #3', '{"board_type": "storage", "location": "Building C"}')
        ]
        
        for username, password, user_type, name, metadata in default_users:
            success = self.create_user(username, password, user_type, name, metadata)
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
