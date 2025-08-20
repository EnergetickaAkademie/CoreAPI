"""
Simple TOML-based user configuration loader for WebControl

This module loads user accounts from a TOML configuration file
and provides them in the format expected by the authentication system.
"""

import toml
import os
from typing import List, Dict, Any, Optional

class UserConfig:
    """Simple user configuration loader"""
    
    def __init__(self, config_file: str = "config/users.toml"):
        """
        Initialize the configuration loader
        
        Args:
            config_file: Path to the TOML configuration file
        """
        self.config_file = config_file
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """Load configuration from TOML file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = toml.load(f)
                print(f"✓ Loaded user configuration from {self.config_file}")
            else:
                print(f"⚠️  Configuration file not found: {self.config_file}")
                print("Using default configuration")
                self.config = self._get_default_config()
        except Exception as e:
            print(f"⚠️  Error loading configuration: {e}")
            print("Using default configuration")
            self.config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration if file is not available"""
        return {
            "lecturers": {
                "lecturer1": {"password": "lecturer123", "name": "Default Lecturer", "group": "group1"}
            },
            "boards": {
                "board1": {"password": "board123", "name": "Default Board", "group": "group1"}
            },
            "groups": {
                "group1": {"name": "Default Group", "max_boards": 10}
            }
        }
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """
        Get all users (both lecturers and boards) in the format expected by SimpleAuth
        
        Returns:
            List of user dictionaries with username, password, user_type, group_id, and name
        """
        users = []
        
        # Add lecturers
        lecturers = self.config.get("lecturers", {})
        for username, info in lecturers.items():
            users.append({
                "username": username,
                "password": info["password"],
                "user_type": "lecturer",
                "group_id": info.get("group", "group1"),
                "name": info.get("name", username)
            })
        
        # Add boards
        boards = self.config.get("boards", {})
        for username, info in boards.items():
            users.append({
                "username": username,
                "password": info["password"],
                "user_type": "board",
                "group_id": info.get("group", "group1"),
                "name": info.get("name", username)
            })
        
        return users
    
    def get_lecturers(self) -> List[Dict[str, Any]]:
        """Get only lecturer users"""
        lecturers = []
        lecturer_config = self.config.get("lecturers", {})
        
        for username, info in lecturer_config.items():
            lecturers.append({
                "username": username,
                "password": info["password"],
                "user_type": "lecturer",
                "group_id": info.get("group", "group1"),
                "name": info.get("name", username)
            })
        
        return lecturers
    
    def get_boards(self) -> List[Dict[str, Any]]:
        """Get only board users"""
        boards = []
        board_config = self.config.get("boards", {})
        
        for username, info in board_config.items():
            boards.append({
                "username": username,
                "password": info["password"],
                "user_type": "board",
                "group_id": info.get("group", "group1"),
                "name": info.get("name", username)
            })
        
        return boards
    
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get a specific user by username"""
        all_users = self.get_all_users()
        for user in all_users:
            if user["username"] == username:
                return user
        return None
    
    def get_groups(self) -> Dict[str, Any]:
        """Get group configuration"""
        return self.config.get("groups", {})
    
    def reload(self):
        """Reload configuration from file"""
        self.load_config()

# Global instance
_user_config = None

def get_user_config(config_file: str = "config/users.toml") -> UserConfig:
    """Get the global user configuration instance"""
    global _user_config
    if _user_config is None:
        _user_config = UserConfig(config_file)
    return _user_config
