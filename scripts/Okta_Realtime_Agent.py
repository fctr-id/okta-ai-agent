#!/usr/bin/env python3

import sys
import asyncio
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Fix import paths - add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Setup logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import settings and required modules
from src.config.settings import settings
from src.core.realtime.okta_realtime_client import get_okta_realtime_deps
from src.core.model_picker import ModelConfig, ModelType
from src.core.realtime.agents.reasoning_agent import routing_agent, ExecutionPlan, RoutingResult
from src.core.realtime.execution_manager import ExecutionManager

async def main():
    """Simple CLI interface for the Okta Realtime Agent."""
    print("\n==== OKTA REAL-TIME AI AGENT ====")
    print("Ask natural language questions about your Okta environment.")
    print("Type 'exit' or 'quit' to exit.")
    print("================================\n")
    
    try:
        # Verify settings first
        print(f"Using Okta org: {settings.OKTA_CLIENT_ORGURL}")
        print(f"API token present: {'Yes' if settings.OKTA_API_TOKEN else 'No'}")
        
        # Create Okta dependencies
        deps = get_okta_realtime_deps("cli-session")
        
        # Create execution manager
        execution_manager = ExecutionManager(deps)
        
        # Main interaction loop
        query_counter = 0
        while True:
            try:
                # Get query from user
                query = input("\nEnter your query (or 'exit' to quit): ")
                
                # Check for exit command
                if query.lower() in ('exit', 'quit'):
                    print("Exiting. Goodbye!")
                    break
                    
                # Skip empty queries
                if not query.strip():
                    continue
                
                # Update query ID
                query_id = f"cli-{query_counter}"
                query_counter += 1
                deps.query_id = query_id
                
                # Step 1: Use coordinator agent to create execution plan
                print("\n1. Creating execution plan...")
                try:
                    # Use run() and make sure to await the coroutine properly
                    response = await routing_agent.run(query)
                    plan_result = response.data
                    
                    # Log the raw LLM output (debug only)
                    logger.debug("Raw LLM Response: %s", response.message if hasattr(response, 'message') else str(response))
                    
                    # Then display the structured plan
                    print(f"\nStructured Execution Plan (Confidence: {plan_result.confidence}%)")
                    print(f"Reasoning: {plan_result.plan.reasoning}")
                    print("\nSteps:")
                    for i, step in enumerate(plan_result.plan.steps):
                        print(f"  {i+1}. Tool: {step.tool_name}")
                        print(f"     Context: {step.query_context}")
                        print(f"     Critical: {'Yes' if step.critical else 'No'}")
                        print(f"     Reason: {step.reason}")
                    
                    # Ask for confirmation
                    proceed = input("\nProceed with execution? (y/n): ").lower() == 'y'
                    if not proceed:
                        print("Execution cancelled.")
                        continue
                        
                except Exception as e:
                    logger.error(f"Planning error: {str(e)}", exc_info=True)
                    print(f"Error creating plan: {str(e)}")
                    continue
                
                # Step 2: Execute the plan
                print("\n2. Executing plan...")
                try:
                    execution_result = await execution_manager.execute_plan(plan_result.plan)
                    
                    # Check if we got an error response
                    if hasattr(execution_result, 'error_type'):
                        print(f"Error: {execution_result.message}")
                        continue
                    
                    # Display execution summary
                    print(f"\nPlan executed successfully!")
                    print(f"Entities queried: {', '.join(execution_result.entities_queried)}")
                    if execution_result.errors:
                        print(f"Warnings/Errors: {len(execution_result.errors)}")
                    
                    # Extract the final result from the last step
                    last_step = list(execution_result.results.values())[-1]
                    final_result = last_step.get('result')
                    
                    # Always show the result
                    print("\nResult:")
                    print("-" * 60)
                    if isinstance(final_result, (dict, list)):
                        print(json.dumps(final_result, indent=2, default=str))
                    else:
                        print(final_result)
                    print("-" * 60)
                    
                except Exception as e:
                    logger.error(f"Execution error: {str(e)}", exc_info=True)
                    print(f"Error executing plan: {str(e)}")
                    
            except KeyboardInterrupt:
                print("\nExiting. Goodbye!")
                break
            except Exception as e:
                logger.error(f"Error: {str(e)}", exc_info=True)
                print(f"Error: {str(e)}")
    except ValueError as e:
        print(f"\nConfiguration error: {e}")
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    # Run the async main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting. Goodbye!")
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}", exc_info=True)
        print(f"Fatal error: {str(e)}")
        sys.exit(1)