#!/usr/bin/env python3
"""
Tako Okta AI Agent v1.0.0-beta - Single Hybrid Mode
Main Entry Point with Intelligent Routing

This is the unified entry point for Tako that intelligently routes queries between:
- Database Mode: For complex queries requiring SQLite database
- Realtime Mode: For real-time API calls and simple operations

The system automatically determines the best execution mode based on query analysis.
"""

import sys
import asyncio
import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import traceback
from typing import Optional, Dict, Any, Union, List
import csv
from datetime import datetime
import argparse

# Setup project paths
project_root = Path(__file__).resolve().parent
sys.path.append(str(project_root))
src_path = project_root / "src"
sys.path.append(str(src_path))

# Load environment variables
load_dotenv(override=True)

# Import core utilities
from src.utils.logging import get_logger, set_correlation_id, generate_correlation_id
from src.utils.error_handling import (
    BaseError, ConfigurationError, ExecutionError, DependencyError, 
    safe_execute_async, format_error_for_user
)
from src.config.settings import settings

# Initialize logger
logger = get_logger(__name__)

def check_virtual_environment() -> bool:
    """Check if running in the correct virtual environment"""
    venv_path = Path(__file__).parent / "venv"
    current_venv = Path(sys.prefix)
    
    # Check if running in any venv
    is_in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    # Check if it's our specific venv
    is_correct_venv = current_venv.resolve() == venv_path.resolve()
    
    return is_in_venv and is_correct_venv

def validate_environment():
    """Validate the running environment"""
    if not check_virtual_environment():
        print("\n⚠️ Error: Virtual environment not activated!")
        print("\nPlease activate your virtual environment:")
        print("1. Open terminal in project root")
        print("2. Run: ")
        if sys.platform == "win32":
            print("   .\\venv\\Scripts\\activate")
        else:
            print("   source venv/bin/activate")
        print("\nThen run this script again.")
        sys.exit(1)
    
    logger.info("Virtual environment validated")

def print_welcome():
    """Print welcome message for Tako v1.0.0-beta"""
    print("\n" + "="*80)
    print("🐙 TAKO - Okta AI Agent v1.0.0-beta (Single Hybrid Mode)")
    print("="*80)
    print("Intelligent Okta Assistant with Unified Database & Realtime Processing")
    print("\nFeatures:")
    print("• 🧠 Smart Mode Detection (Database vs Realtime)")
    print("• 🔍 Natural Language Query Processing")
    print("• 📊 SQLite Database Analysis")
    print("• ⚡ Real-time Okta API Integration")
    print("• 🤖 Multiple AI Model Support")
    print("• 📈 Comprehensive Logging & Monitoring")
    print("\nEnter your questions naturally - Tako will determine the best approach!")
    print("="*80 + "\n")

def setup_argument_parser():
    """Setup command line argument parser"""
    parser = argparse.ArgumentParser(
        description="Tako Okta AI Agent v1.0.0-beta - Single Hybrid Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --query "How many users are in the Engineering group?"
  python main.py --mode database --query "Show me all inactive users"
  python main.py --mode realtime --query "Get current user sessions"
  python main.py --interactive  # Start interactive mode
        """
    )
    
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="Natural language query to process"
    )
    
    parser.add_argument(
        "--mode", "-m",
        choices=["auto", "database", "realtime"],
        default="auto",
        help="Execution mode (auto=intelligent routing, default: auto)"
    )
    
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start interactive mode"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--output-format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format for results (default: table)"
    )
    
    return parser

async def main():
    """Main entry point for Tako v1.0.0-beta Single Hybrid Mode"""
    try:
        # Validate environment
        validate_environment()
        
        # Set correlation ID for this session
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        
        logger.info(f"Starting Tako v1.0.0-beta - Session ID: {correlation_id}")
        
        # Parse command line arguments
        parser = setup_argument_parser()
        args = parser.parse_args()
        
        # Set debug logging if requested
        if args.debug:
            import logging
            logging.getLogger().setLevel(logging.DEBUG)
            logger.debug("Debug logging enabled")
        
        # Print welcome message
        print_welcome()
        
        # The modern architecture uses the web API and Modern Execution Manager
        # Start the web server instead of the deprecated hybrid agent
        print("🚀 Starting Okta AI Agent Web Server...")
        print("📝 Access the web interface at: http://localhost:8001")
        print("🔄 Use Ctrl+C to stop the server")
        
        # Import and start the FastAPI server
        import uvicorn
        from src.api.main import app
        
        # Start the server
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=8001,
            log_level="info",
            reload=args.debug  # Enable reload in debug mode
        )
        server = uvicorn.Server(config)
        await server.serve()
            
        logger.info("Okta AI Agent session completed successfully")
        
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye! Thanks for using the Okta AI Agent!")
        logger.info("User interrupted session")
    except Exception as e:
        error_msg = format_error_for_user(e)
        print(f"\n❌ Error: {error_msg}")
        logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
