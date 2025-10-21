#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Okta ReAct Agent Test Script

This test validates the ReAct agent workflow with 6 tools for hybrid SQLite + API queries.
Tests the reasoning and acting pattern for query execution.

Expected workflow:
1. Agent loads SQLite database schema
2. Agent determines if data is in database or needs API
3. Agent loads comprehensive API endpoints if needed
4. Agent filters to specific entities
5. Agent generates test code with LIMIT 3
6. Agent executes and inspects results
7. Agent generates production code
8. Returns ExecutionResult
"""

import asyncio
import sys
import json
import os
import time
from pathlib import Path

# Change to project root directory (from scripts folder to parent)
project_root = Path(__file__).parent.parent
os.chdir(str(project_root))
sys.path.insert(0, str(project_root))

from src.core.agents.one_react_agent import execute_react_query, ReactAgentDependencies
from src.core.okta.client.base_okta_api_client import OktaAPIClient
import sqlite3

def check_database_health(db_path: Path) -> bool:
    """
    Check if the SQLite database exists and is populated with users.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        bool: True if database exists and has users (>= 1), False otherwise
    """
    try:
        if not db_path.exists():
            print(f"⚠️ Database file not found: {db_path}")
            return False
        
        # Check if database is accessible and has users
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            cursor = conn.cursor()
            
            # Check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not cursor.fetchone():
                print("⚠️ Users table not found in database")
                return False
            
            # Check if users table has at least 1 record
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            print(f"✅ Database health check: Found {user_count} users in database")
            return user_count >= 1
            
    except Exception as e:
        print(f"⚠️ Database health check failed: {e}")
        return False


async def run_react_test_and_save(query: str):
    """Run the ReAct agent test and save results to file"""
    print(f"🚀 Running ReAct agent test with query: {query}")
    print("=" * 80)
    
    start_time = time.time()
    
    # Initialize Okta client
    print("Initializing Okta client...")
    okta_client = OktaAPIClient()
    
    # Initialize SQLite connection
    print("Initializing SQLite database...")
    db_path = project_root / "sqlite_db" / "okta_sync.db"
    
    # Check database health
    db_healthy = check_database_health(db_path)
    
    # Modify query if database is not healthy (force API-only mode)
    modified_query = query
    if not db_healthy:
        print("⚠️ Database unavailable or empty - forcing API-only mode")
        modified_query = f"{query}. Do NOT use SQL and only use APIs"
        print(f"📝 Modified query: {modified_query}")
    else:
        print("✅ Database is healthy - SQL and API modes both available")
    
    # Still establish connection for agent (even if DB is unhealthy, agent may need schema info)
    conn = sqlite3.connect(str(db_path))
    
    # Schema will be loaded on-demand by the agent via Tool 1
    print("✅ Database connection ready (schema will be loaded on-demand)")
    
    # Load API endpoints
    print("Loading API endpoints...")
    
    # Load lightweight reference for Tool 2 (minimal operations list)
    lightweight_file = project_root / "src" / "data" / "schemas" / "lightweight_onereact.json"
    
    # Load full endpoint reference for Tool 3 (detailed endpoint info)
    full_endpoints_file = project_root / "src" / "data" / "schemas" / "Okta_API_entitity_endpoint_reference_GET_ONLY.json"
    
    try:
        # Load lightweight reference (minimal operations list in dot notation)
        with open(lightweight_file, 'r', encoding='utf-8') as f:
            lightweight_data = json.load(f)
        
        # Load full endpoint details
        with open(full_endpoints_file, 'r', encoding='utf-8') as f:
            full_api_data = json.load(f)
            endpoints = full_api_data.get('endpoints', [])
        
        print(f"✅ Loaded {len(lightweight_data.get('operations', []))} operations from lightweight reference (dot notation)")
        print(f"✅ Loaded {len(endpoints)} full endpoint details")
    except Exception as e:
        print(f"⚠️ Warning loading endpoints: {e}")
        lightweight_data = {"operations": [], "sql_tables": []}
        endpoints = []
    
    # Operation mapping is not needed for ReAct agent - it uses endpoints directly
    print("Skipping operation mapping (not needed for ReAct agent)...")
    operation_mapping = {}
    
    # Create correlation ID
    correlation_id = f"react_test_{int(time.time())}"
    
    # Create dependencies
    deps = ReactAgentDependencies(
        correlation_id=correlation_id,
        endpoints=endpoints,  # Full endpoint details for Tool 3
        lightweight_entities=lightweight_data,  # Minimal operations list for Tool 2 (new format)
        okta_client=okta_client,
        sqlite_connection=conn,
        operation_mapping=operation_mapping,
        user_query=modified_query  # Use modified query with API-only instruction if DB is unhealthy
    )
    
    print()
    print("=" * 80)
    print("EXECUTING REACT AGENT")
    print("=" * 80)
    
    # Execute query
    try:
        result, usage = await execute_react_query(modified_query, deps)
        
        end_time = time.time()
        response_time = end_time - start_time
        
        print()
        print("=" * 80)
        print("📊 EXECUTION RESULTS:")
        print("=" * 80)
        print(f"Success: {result.success}")
        print(f"Execution Plan: {result.execution_plan[:200]}..." if len(result.execution_plan) > 200 else f"Execution Plan: {result.execution_plan}")
        print(f"Steps Taken: {len(result.steps_taken)}")
        for i, step in enumerate(result.steps_taken, 1):
            print(f"  {i}. {step}")
        print(f"Response time: {response_time:.1f}s")
        
        # Print token usage
        if usage:
            print()
            print("=" * 80)
            print("🪙 TOKEN USAGE:")
            print("=" * 80)
            print(f"Input tokens:  {usage.request_tokens:,}")
            print(f"Output tokens: {usage.response_tokens:,}")
            print(f"Total tokens:  {usage.total_tokens:,}")
            print(f"API requests:  {usage.requests}")
            print("=" * 80)
        
        if result.error:
            print(f"Error: {result.error}")
        
        if result.results:
            print(f"\nResults preview: {str(result.results)[:500]}...")
        
        if result.complete_production_code:
            print(f"\n📜 COMPLETE PRODUCTION CODE:")
            print("="*80)
            print(result.complete_production_code)
            print("="*80)
        else:
            print(f"\n⚠️ WARNING: complete_production_code is empty or missing!")
        
        print()
        
        # Save the generated code to a Python file
        timestamp = int(time.time())
        
        if result.complete_production_code:
            # Save production code to src/data/testing folder
            code_output_dir = project_root / "src" / "data" / "testing"
            code_output_dir.mkdir(parents=True, exist_ok=True)
            code_output_file = code_output_dir / f"generated_code_{timestamp}.py"
            
            with open(code_output_file, 'w', encoding='utf-8') as f:
                f.write(result.complete_production_code)
            
            print(f"💾 Generated code saved to: {code_output_file}")
            print(f"   You can now run: python {code_output_file}")
        else:
            print(f"⚠️ No production code generated - skipping code file creation")
            code_output_file = None
        
        # Save a summary metadata file (lightweight JSON)
        metadata_output_dir = project_root / "src" / "data" / "testing"
        metadata_output_dir.mkdir(parents=True, exist_ok=True)
        metadata_file = metadata_output_dir / f"test_metadata_{timestamp}.json"
        
        test_metadata = {
            "timestamp": timestamp,
            "query": query,
            "response_time": response_time,
            "correlation_id": correlation_id,
            "success": result.success,
            "execution_plan": result.execution_plan,
            "steps_taken": result.steps_taken,
            "error": result.error,
            "total_steps": len(result.steps_taken),
            "code_file": str(code_output_file) if code_output_file else None
        }
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(test_metadata, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"💾 Test metadata saved to: {metadata_file}")
        print()
        
        # Brief summary
        print("📝 TEST SUMMARY:")
        print(f"Query: {query}")
        print(f"Status: {'✅ SUCCESS' if result.success else '❌ FAILED'}")
        print(f"Time taken: {response_time:.1f}s")
        if usage:
            print(f"Token usage: {usage.request_tokens:,} input / {usage.response_tokens:,} output / {usage.total_tokens:,} total")
        if code_output_file:
            print(f"Generated code: {code_output_file}")
        
        return test_metadata
        
    except Exception as e:
        end_time = time.time()
        response_time = end_time - start_time
        
        print()
        print("=" * 80)
        print("❌ EXECUTION FAILED")
        print("=" * 80)
        print(f"Error: {str(e)}")
        print(f"Response time: {response_time:.1f}s")
        print()
        
        import traceback
        print("Traceback:")
        print(traceback.format_exc())
        
        # Save error metadata (lightweight)
        timestamp = int(time.time())
        metadata_output_dir = project_root / "src" / "data" / "testing"
        metadata_output_dir.mkdir(parents=True, exist_ok=True)
        metadata_file = metadata_output_dir / f"test_metadata_{timestamp}.json"
        
        test_metadata = {
            "timestamp": timestamp,
            "query": query,
            "response_time": response_time,
            "correlation_id": correlation_id,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(test_metadata, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"💾 Error metadata saved to: {metadata_file}")
        
        return test_metadata

def main():
    if len(sys.argv) != 2:
        print("Usage: python okta_react_agent_test.py \"<query>\"")
        print("\nExample test queries:")
        print("1. \"Find all users in the Admins group\"")
        print("2. \"Show me all groups and their member counts\"")
        print("3. \"List all applications\"")
        print("4. \"Find users logged in the last 10 days\"")
        print("5. \"Get all users with super admin role\"")
        sys.exit(1)
    
    query = sys.argv[1]
    result = asyncio.run(run_react_test_and_save(query))
    
    # Exit with 0 for success, 1 for failure based on execution success
    success = result.get('success', False)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
