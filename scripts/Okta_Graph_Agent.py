#!/usr/bin/env python3
import asyncio
import argparse
import logging
from typing import Dict, Any, List
import json
import os
import sys
import uuid

# Add root directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Add to workflow_executor.py just after imports:


from src.core.realtime_graph.agents.reasoning_agent import routing_agent, create_execution_plan
from src.core.realtime_graph.graph_manager import okta_graph_manager


# Print information about file paths
import os
print(f"WORKFLOW_EXECUTOR_PATH: {os.path.abspath(__file__)}")
print(f"STATE_RESOLVER_PATH: {os.path.abspath(os.path.join(os.path.dirname(__file__), 'state_resolver.py'))}")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("okta_graph_cli")

async def process_query(query: str, verbose: bool = False) -> Dict[str, Any]:
    """
    Process a natural language query using the Okta graph system.
    
    Args:
        query: User's natural language query
        verbose: Whether to print detailed execution information
        
    Returns:
        Dict with results and execution information
    """
    # Generate a unique query ID that's more readable
    query_id = f"cli-{uuid.uuid4().hex[:7]}"
    logger.info(f"[{query_id}] Processing query: {query}")
    
    # Step 1: Create an execution plan using the reasoning agent
    logger.info(f"[{query_id}] Creating execution plan...")
    plan_data, raw_response = await create_execution_plan(query)
    
    if verbose:
        print("\n=== Execution Plan ===")
        print(f"Reasoning: {plan_data.plan.reasoning}")
        print("\nNodes to execute:")
        for i, step in enumerate(plan_data.plan.steps):
            print(f"{i+1}. {step.tool_name}: {step.reason}")
            print(f"   Parameters: {json.dumps(step.query_context, indent=2)}")
    
    # Step 2: Execute the plan using the graph manager
    logger.info(f"[{query_id}] Executing plan with {len(plan_data.plan.steps)} nodes...")
    
    # In the process_query function, modify this section:
    execution_steps = []
    for step in plan_data.plan.steps:
        # The query_context could be a dict, a string, or a string representation of a dict
        if isinstance(step.query_context, dict):
            params = step.query_context
        else:
            # Check if string looks like a dictionary (starts with { and ends with })
            if isinstance(step.query_context, str):
                if step.query_context.strip().startswith('{') and step.query_context.strip().endswith('}'):
                    try:
                        # Try to safely evaluate it as a Python literal
                        import ast
                        params = ast.literal_eval(step.query_context)
                        logger.info(f"[{query_id}] Converted string dict to actual dict for {step.tool_name}")
                    except (SyntaxError, ValueError) as e:
                        logger.warning(f"[{query_id}] Failed to parse dict-like string: {e}")
                        # Fall back to tool-specific handling
                        tool_name = step.tool_name.lower()
                        if tool_name == "search_users":
                            params = {"search_query": step.query_context}
                        else:
                            params = {"query": step.query_context}
                else:
                    # Map string query_context to the correct parameter name based on tool type
                    tool_name = step.tool_name.lower()
                    if tool_name == "search_users":
                        params = {"search_query": step.query_context}
                    elif tool_name == "get_user":
                        params = {"user_id": step.query_context}
                    elif tool_name == "get_user_groups":
                        params = {"user_id": step.query_context}
                    else:
                        # Default fallback
                        params = {"query": step.query_context}
            else:
                # For non-string, non-dict values
                params = {"value": step.query_context}
        
        execution_steps.append({
            "type": step.tool_name.lower(),
            "params": params
        })
    
    result = await okta_graph_manager.execute_plan(execution_steps, query_id=query_id)
    
    # Step 3: Format and return the results
    logger.info(f"[{query_id}] Execution complete")
    
    return {
        "query": query,
        "plan": plan_data.model_dump() if hasattr(plan_data, "dict") else plan_data.model_dump(),
        "execution_result": result,
        "query_id": query_id
    }

async def interactive_mode():
    """Run the CLI in interactive mode."""
    print("Okta Graph Agent - Interactive Mode")
    print("Type 'exit' or 'quit' to end the session")
    print("Type 'verbose' to toggle verbose mode")
    
    verbose = False
    
    while True:
        try:
            # Get user input
            query = input("\nEnter your query: ").strip()
            
            # Check for exit commands
            if query.lower() in ("exit", "quit"):
                print("Exiting...")
                break
                
            # Check for verbose toggle
            if query.lower() == "verbose":
                verbose = not verbose
                print(f"Verbose mode: {'ON' if verbose else 'OFF'}")
                continue
                
            # Skip empty queries
            if not query:
                continue
                
            # Process the query
            result = await process_query(query, verbose)
            execution_result = result["execution_result"]
            
            # Print the final result
            print("\n=== Results ===")
            if execution_result.get("errors"):
                print("Errors occurred during execution:")
                for error in execution_result["errors"]:
                    print(f"- {error}")
            
            if execution_result.get("completed") is False:
                print("\nExecution did not complete successfully.")
            
            # Format and print the final result - updated to handle both formats
            final_result = execution_result.get("final_result")
            
            # Handle case where no final result is found
            if final_result is None:
                # Check if there's any results we can show from the last step
                if execution_result.get("results") and len(execution_result["results"]) > 0:
                    final_result = execution_result["results"][-1].get("result")
                    print("\nNo final result found. Showing last operation result:")
            
            # Display formatted result
            if isinstance(final_result, list):
                print(f"\nFound {len(final_result)} results:")
                for i, item in enumerate(final_result[:5]):  # Limit display to 5 items
                    if isinstance(item, dict) and "profile" in item:
                        profile = item["profile"]
                        print(f"\nUser: {profile.get('firstName', '')} {profile.get('lastName', '')}")
                        print(f"Email: {profile.get('email', '')}")
                        print(f"Status: {item.get('status', '')}")
                    else:
                        print(f"{i+1}. {str(item)[:100]}")
                
                if len(final_result) > 5:
                    print(f"...and {len(final_result) - 5} more results")
            elif isinstance(final_result, dict):
                if "profile" in final_result:
                    profile = final_result["profile"]
                    print(f"\nUser: {profile.get('firstName', '')} {profile.get('lastName', '')}")
                    print(f"Email: {profile.get('email', '')}")
                    print(f"Status: {final_result.get('status', '')}")
                else:
                    # Try to extract the most important information
                    important_fields = {k: v for k, v in final_result.items() 
                                      if k in ('id', 'name', 'description', 'title', 'error')}
                    print(f"\nResult: {json.dumps(important_fields or final_result, indent=2)}")
            elif final_result is not None:
                print(f"\nResult: {final_result}")
            else:
                print("\nNo results to display.")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {str(e)}")
            if verbose:
                import traceback
                traceback.print_exc()

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(description="Okta Graph Agent CLI")
    parser.add_argument("--query", "-q", help="Query to execute (if not provided, runs in interactive mode)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    
    args = parser.parse_args()
    
    if args.query:
        # Execute single query mode
        asyncio.run(process_query(args.query, args.verbose))
    else:
        # Run interactive mode
        asyncio.run(interactive_mode())

if __name__ == "__main__":
    main()