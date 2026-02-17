#!/usr/bin/env python3
"""
Create a bot user for Slack integration.

Usage:
    python scripts/create_bot_user.py --username tako_slack_bot --password <secure-password>

This creates an auth_users entry that the Slack bot can use
to authenticate with the TakoAI API.
"""

import asyncio
import argparse
import sys
import secrets
from pathlib import Path

# Setup project paths
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.core.okta.sync.operations import DatabaseOperations
from src.core.okta.sync.models import UserRole
from src.core.security.jwt import create_access_token


async def create_bot_user(username: str, password: str):
    """Create a bot user and generate an access token."""
    db = DatabaseOperations()
    await db.init_db()

    async with db.get_session() as session:
        # Check if user already exists
        existing = await db.get_auth_user(session, username)
        if existing:
            print(f"User '{username}' already exists (id={existing.id})")
            print("Generating new access token...")
        else:
            # Create the user
            user = await db.create_auth_user(
                session, username, password, role=UserRole.ADMIN
            )
            await session.commit()
            print(f"Bot user '{username}' created (id={user.id})")

    # Generate a long-lived token for the bot
    from datetime import timedelta
    token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(days=365),
    )
    print(f"\nBot Access Token (valid for 1 year):\n{token}")
    print("\nSet this as your SLACK_BOT_AUTH_TOKEN or use in Authorization header:")
    print(f"  Authorization: Bearer {token}")


async def main():
    parser = argparse.ArgumentParser(description="Create a bot user for TakoAI")
    parser.add_argument(
        "--username",
        default="tako_slack_bot",
        help="Bot username (default: tako_slack_bot)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Bot password (auto-generated if not provided)",
    )
    args = parser.parse_args()

    password = args.password or secrets.token_urlsafe(32)
    if not args.password:
        print(f"Generated password: {password}")

    await create_bot_user(args.username, password)


if __name__ == "__main__":
    asyncio.run(main())
