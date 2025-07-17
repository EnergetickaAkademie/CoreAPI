#!/usr/bin/env python3
"""
Configuration loader for WebControl groups and users
Loads users and groups from TOML configuration file
"""

import toml
import os
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class BoardConfig:
    username: str
    password: str
    board_id: int
    name: str
    type: str
    location: str
    group_id: str

@dataclass
class LecturerConfig:
    username: str
    password: str
    name: str
    email: str
    department: str
    group_id: str

@dataclass
class GroupConfig:
    group_id: str
    name: str
    description: str
    lecturer: LecturerConfig
    boards: List[BoardConfig]

class ConfigLoader:
    """Loads and manages configuration from TOML file"""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            # Look for config file in parent directory (project root)
            src_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(src_dir))  # Go up two levels from src
            self.config_path = os.path.join(project_root, 'users_config.toml')
        else:
            self.config_path = config_path
            
        self.groups: Dict[str, GroupConfig] = {}
        self.users: Dict[str, dict] = {}  # username -> user info
        self.board_to_group: Dict[int, str] = {}  # board_id -> group_id
        self.username_to_group: Dict[str, str] = {}  # username -> group_id
        
        self.load_config()
    
    def load_config(self):
        """Load configuration from TOML file"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file {self.config_path} not found")
        
        try:
            config = toml.load(self.config_path)
            self._parse_config(config)
        except Exception as e:
            raise ValueError(f"Failed to parse configuration: {e}")
    
    def _parse_config(self, config: dict):
        """Parse loaded configuration"""
        groups_config = config.get('groups', {})
        
        for group_id, group_data in groups_config.items():
            # Parse lecturer
            lecturer_data = group_data.get('lecturer', {})
            lecturer = LecturerConfig(
                username=lecturer_data['username'],
                password=lecturer_data['password'],
                name=lecturer_data['name'],
                email=lecturer_data['email'],
                department=lecturer_data['department'],
                group_id=group_id
            )
            
            # Parse boards
            boards = []
            boards_data = group_data.get('boards', [])
            for board_data in boards_data:
                board = BoardConfig(
                    username=board_data['username'],
                    password=board_data['password'],
                    board_id=board_data['board_id'],
                    name=board_data['name'],
                    type=board_data['type'],
                    location=board_data['location'],
                    group_id=group_id
                )
                boards.append(board)
                
                # Add to mappings
                self.board_to_group[board.board_id] = group_id
                self.username_to_group[board.username] = group_id
            
            # Create group
            group = GroupConfig(
                group_id=group_id,
                name=group_data['name'],
                description=group_data['description'],
                lecturer=lecturer,
                boards=boards
            )
            
            self.groups[group_id] = group
            
            # Add lecturer to mappings
            self.username_to_group[lecturer.username] = group_id
            
            # Add users to authentication database
            self._add_lecturer_to_users(lecturer)
            for board in boards:
                self._add_board_to_users(board)
    
    def _add_lecturer_to_users(self, lecturer: LecturerConfig):
        """Add lecturer to users database"""
        metadata = {
            "department": lecturer.department,
            "email": lecturer.email,
            "group_id": lecturer.group_id
        }
        
        self.users[lecturer.username] = {
            "username": lecturer.username,
            "password": lecturer.password,
            "name": lecturer.name,
            "user_type": "lecturer",
            "metadata": metadata
        }
    
    def _add_board_to_users(self, board: BoardConfig):
        """Add board to users database"""
        metadata = {
            "board_type": board.type,
            "location": board.location,
            "board_id": board.board_id,
            "group_id": board.group_id
        }
        
        self.users[board.username] = {
            "username": board.username,
            "password": board.password,
            "name": board.name,
            "user_type": "board",
            "metadata": metadata
        }
    
    def get_user_group(self, username: str) -> Optional[str]:
        """Get group ID for a username"""
        return self.username_to_group.get(username)
    
    def get_board_group(self, board_id: int) -> Optional[str]:
        """Get group ID for a board ID"""
        return self.board_to_group.get(board_id)
    
    def get_group_config(self, group_id: str) -> Optional[GroupConfig]:
        """Get group configuration"""
        return self.groups.get(group_id)
    
    def get_group_boards(self, group_id: str) -> List[BoardConfig]:
        """Get all boards for a group"""
        group = self.groups.get(group_id)
        return group.boards if group else []
    
    def get_all_users(self) -> Dict[str, dict]:
        """Get all users for authentication"""
        return self.users.copy()
    
    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Authenticate user and return user info"""
        user = self.users.get(username)
        if user and user['password'] == password:
            # Return user info without password
            user_info = user.copy()
            del user_info['password']
            return user_info
        return None

# Global configuration instance
config_loader = ConfigLoader()
