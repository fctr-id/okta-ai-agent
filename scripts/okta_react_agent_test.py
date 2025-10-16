#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Okta ReAct Agent Test Script

This test validates the ReAct agent workflow with 7 tools for hybrid GraphDB + API queries.
Tests the reasoning and acting pattern for query execution.

Expected workflow:
1. Agent loads GraphDB schema
2. Agent determines if data is in GraphDB or needs API
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
from src.core.okta.graph_db.schema_v2_enhanced import get_graph_schema_description
from src.core.okta.graph_db.version_manager import GraphDBVersionManager
import kuzu

async def run_react_test_and_save(query: str):
    """Run the ReAct agent test and save results to file"""
    print(f"🚀 Running ReAct agent test with query: {query}")
    print("=" * 80)
    
    start_time = time.time()
    
    # Initialize Okta client
    print("Initializing Okta client...")
    okta_client = OktaAPIClient()
    
    # Initialize Kuzu connection using version manager
    print("Initializing Kuzu GraphDB...")
    version_manager = GraphDBVersionManager()
    db_path = version_manager.get_current_db_path()
    
    if not Path(db_path).exists():
        print(f"⚠️ WARNING: GraphDB not found at {db_path}")
        print("The agent will fall back to API-only mode")
    else:
        print(f"✅ Using GraphDB: {db_path}")
    
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    
    # Load graph schema
    print("Loading graph schema...")
    try:
        # Get the full schema description text - it already has everything we need!
        graph_schema_text = get_graph_schema_description()
        
        # The schema text is comprehensive and LLM-optimized
        # It includes all node types, relationships, properties, and examples
        # We'll pass it directly to the agent as-is
        graph_schema = {
            "schema_text": graph_schema_text,
            # Note: The agent will parse what it needs from the schema_text
            # The schema_text already contains everything in a well-formatted way
        }
        print(f"✅ Loaded comprehensive schema description ({len(graph_schema_text)} chars)")
        
    except Exception as e:
        print(f"⚠️ Warning loading schema: {e}")
        graph_schema = {
            "schema_text": ""
        }
    
    # Load API endpoints
    print("Loading API endpoints...")
    
    # Load lightweight reference for Tool 2 (entity list)
    lightweight_file = project_root / "src" / "data" / "schemas" / "lightweight_api_reference.json"
    
    # Load full endpoint reference for Tool 3 (detailed endpoint info)
    full_endpoints_file = project_root / "src" / "data" / "schemas" / "Okta_API_entitity_endpoint_reference_GET_ONLY.json"
    
    try:
        # Load lightweight reference (entity-operation mapping)
        with open(lightweight_file, 'r', encoding='utf-8') as f:
            lightweight_data = json.load(f)
        
        # Load full endpoint details
        with open(full_endpoints_file, 'r', encoding='utf-8') as f:
            full_api_data = json.load(f)
            endpoints = full_api_data.get('endpoints', [])
        
        print(f"✅ Loaded {len(lightweight_data.get('entities', {}))} entities from lightweight reference")
        print(f"✅ Loaded {len(endpoints)} full endpoint details")
    except Exception as e:
        print(f"⚠️ Warning loading endpoints: {e}")
        lightweight_data = {"entities": {}}
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
        lightweight_entities=lightweight_data.get('entities', {}),  # Lightweight entity list for Tool 2
        graph_schema=graph_schema,
        okta_client=okta_client,
        kuzu_connection=conn,
        operation_mapping=operation_mapping,
        user_query=query
    )
    
    print()
    print("=" * 80)
    print("EXECUTING REACT AGENT")
    print("=" * 80)
    
    # Execute query
    try:
        result = await execute_react_query(query, deps)
        
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
        print(f"Steps executed: {len(result.steps_taken)}")
        print(f"Time taken: {response_time:.1f}s")
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
