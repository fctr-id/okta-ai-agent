#!/usr/bin/env python
"""
Admin Password Reset Tool for Okta AI Agent

This script allows resetting the admin password or creating a new admin user
in case you're locked out of the application.

Usage:
  python forgot_admin_password.py

The script will prompt for a new admin username and password, then update the database.
"""

import os
import sys
import re
import getpass
import sqlite3
from pathlib import Path
from datetime import datetime

# Make sure we can import from src
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.append(str(project_root))

from src.config.settings import settings
from src.core.helpers.argon2_hash import hash_password

def validate_password(password):
    """Validate password meets strength requirements"""
    if len(password) < 12:
        return False, "Password must be at least 12 characters"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, "Password must contain at least one special character"
    
    return True, "Password meets requirements"

def main():
    print("\n========================================")
    print("Okta AI Agent - Admin Password Reset Tool")
    print("========================================\n")
    
    try:
        # Get database path from settings
        db_path = settings.SQLITE_PATH
        if not os.path.exists(db_path):
            print(f"Error: Database not found at {db_path}")
            print("Please run the application first to initialize the database.")
            return 1
        
        # Connect to the database
        print(f"Connecting to database at {db_path}")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check if auth_users table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='auth_users'")
        if not cursor.fetchone():
            print("Creating auth_users table as it doesn't exist...")
            cursor.execute('''
            CREATE TABLE auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'admin',
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                setup_completed BOOLEAN NOT NULL DEFAULT 1,
                last_login TIMESTAMP NULL,
                login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMP NULL
            )
            ''')
            print("Table created successfully.")
        
        # Prompt for username
        username = input("Enter admin username (min 3 characters): ").strip()
        while len(username) < 3:
            print("Username must be at least 3 characters.")
            username = input("Enter admin username (min 3 characters): ").strip()
        
        # Check if user exists
        cursor.execute("SELECT id FROM auth_users WHERE username = ?", (username,))
        user_exists = cursor.fetchone()
        
        # Prompt for password (hidden input)
        while True:
            password = getpass.getpass("Enter new password: ")
            valid, message = validate_password(password)
            if not valid:
                print(f"Invalid password: {message}")
                continue
            
            confirm = getpass.getpass("Confirm new password: ")
            if password != confirm:
                print("Passwords do not match. Try again.")
                continue
            
            break
        
        # Hash the password
        password_hash = hash_password(password)
        now = datetime.now().isoformat()
        
        if user_exists:
            # Update existing user
            cursor.execute(
                '''
                UPDATE auth_users
                SET password_hash = ?, updated_at = ?, is_active = 1, 
                    login_attempts = 0, locked_until = NULL, setup_completed = 1
                WHERE username = ?
                ''', 
                (password_hash, now, username)
            )
            print(f"\nAdmin user '{username}' updated successfully.")
        else:
            # Create new admin user
            cursor.execute(
                '''
                INSERT INTO auth_users 
                (username, password_hash, role, is_active, created_at, updated_at, setup_completed)
                VALUES (?, ?, 'admin', 1, ?, ?, 1)
                ''',
                (username, password_hash, now, now)
            )
            print(f"\nNew admin user '{username}' created successfully.")
        
        # Commit changes
        conn.commit()
        print("You can now log in to the application with these credentials.")
        
        return 0
    
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        # Close the database connection
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    sys.exit(main())