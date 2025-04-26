#!/usr/bin/env python3
"""
Okta Realtime AI Agent

This script provides a CLI interface for interacting with Okta using natural language.
It processes queries, creates execution plans, and runs them against the Okta API.
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

# Fix import paths - add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Import centralized logging configuration
from src.utils.logging import get_logger, set_correlation_id, get_default_log_dir, generate_correlation_id
from src.utils.error_handling import (
    BaseError, ConfigurationError, ExecutionError, DependencyError, 
    safe_execute_async, format_error_for_user
)

# Create logs directory using the utility
logs_dir = get_default_log_dir()

# Initialize logger (correlation ID is already set in logging.py)
logger = get_logger(__name__)

# Load environment variables
load_dotenv()
logger.debug("Environment variables loaded")

# Import settings and required modules
try:
    from src.config.settings import settings
    from src.core.realtime.okta_realtime_client import get_okta_realtime_deps
    from src.core.model_picker import ModelConfig, ModelType
    from src.core.realtime.agents.reasoning_agent import routing_agent, ExecutionPlan
    from src.core.realtime.execution_manager import ExecutionManager
except ImportError as e:
    error = DependencyError(
        message="Could not import required modules",
        dependency="core modules",
        original_exception=e
    )
    error.log()
    print(f"Error: {format_error_for_user(error)}. Please check your installation.")
    sys.exit(1)


class OktaRealtimeAgentCLI:
    """CLI interface for the Okta Realtime Agent."""
    
    def __init__(self):
        """Initialize the CLI interface."""
        self.deps = None
        self.execution_manager = None
    
    async def initialize(self) -> bool:
        """
        Initialize Okta dependencies and verify configuration.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Verify Okta settings
            logger.debug("Verifying Okta settings")
            if not settings.OKTA_CLIENT_ORGURL:
                raise ConfigurationError(
                    message="Okta organization URL not configured",
                    config_key="OKTA_CLIENT_ORGURL"
                )
            if not settings.OKTA_API_TOKEN:
                raise ConfigurationError(
                    message="Okta API token not configured",
                    config_key="OKTA_API_TOKEN"
                )
                
            # Create Okta dependencies
            logger.debug("Creating Okta dependencies")
            self.deps = get_okta_realtime_deps("cli-session")
            
            # Create execution manager
            self.execution_manager = ExecutionManager(self.deps)
            
            return True
            
        except ConfigurationError as e:
            e.log()
            print(f"\n{format_error_for_user(e)}")
            print("Please check your .env file or environment variables.")
            return False
            
        except Exception as e:
            error = BaseError(
                message="Failed to initialize Okta agent",
                original_exception=e
            )
            error.log()
            print(f"\n{format_error_for_user(error)}")
            return False
    
    async def process_query(self, query: str) -> None:
        """
        Process a single user query.
        
        Args:
            query: The natural language query from the user
        """
        # Generate a unique correlation ID for this query
        query_id = generate_correlation_id("q")
        self.deps.query_id = query_id
        
        # Set correlation ID for this query's logs
        set_correlation_id(query_id)
        
        try:
            # Execute the query workflow
            await self._create_and_execute_plan(query)
                
        except KeyboardInterrupt:
            logger.info("Query processing interrupted by user")
            print("\nQuery cancelled.")
            
        except Exception as e:
            error = ExecutionError(
                message="Error processing query",
                original_exception=e,
                context={"query": query}
            )
            error.log()
            print(f"\n{format_error_for_user(error)}")
            print("Please try again with a different query.")
    
    async def _create_and_execute_plan(self, query: str) -> None:
        """
        Create an execution plan and execute it.
        
        Args:
            query: User query to execute
        """
        # Phase 1: Plan Creation
        plan_result, error = await safe_execute_async(
            self._create_execution_plan,
            query,
            error_message="Failed to create execution plan",
            log_error=True
        )
        
        if error or not plan_result:
            if error:
                print(f"\n{format_error_for_user(error)}")
            return
            
        # Phase 2: Ask for confirmation
        if not self._confirm_execution():
            logger.info("User cancelled plan execution")
            print("Execution cancelled.")
            return
            
        # Phase 3: Plan Execution
        await self._execute_plan(plan_result.plan)
    
    async def _create_execution_plan(self, query: str) -> Optional[Any]:
        """
        Create an execution plan from the user query.
        
        Args:
            query: The user's natural language query
            
        Returns:
            Execution plan or None if planning failed
        """
        start_time = time.time()
        print("\n1. Creating execution plan...")
        logger.info(f"Creating execution plan for query: {query}")
        
        # Use routing agent to create plan
        response = await routing_agent.run(query)
        plan_result = response.output
        
        # Log the execution plan details
        logger.debug(f"Plan created with {len(plan_result.plan.steps)} steps")
        
        # Display execution time
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"Plan creation took {elapsed_ms}ms")
        
        # Display the plan
        self._display_execution_plan(plan_result)
        
        return plan_result
    
    def _display_execution_plan(self, plan_result: Any) -> None:
        """
        Display the execution plan in a user-friendly format.
        
        Args:
            plan_result: The plan result from the routing agent
        """
        print(f"\nStructured Execution Plan (Confidence: {plan_result.confidence}%)")
        print(f"Reasoning: {plan_result.plan.reasoning}")
        print("\nSteps:")
        
        for i, step in enumerate(plan_result.plan.steps):
            print(f"  {i+1}. Tool: {step.tool_name}")
            print(f"     Context: {step.query_context}")
            print(f"     Critical: {'Yes' if step.critical else 'No'}")
            print(f"     Reason: {step.reason}")
    
    def _confirm_execution(self) -> bool:
        """
        Ask the user to confirm plan execution.
        
        Returns:
            True if the user confirms, False otherwise
        """
        try:
            return input("\nProceed with execution? (y/n): ").lower().startswith('y')
        except EOFError:
            return False
    
    async def _execute_plan(self, plan: ExecutionPlan) -> None:
        """
        Execute the created plan and display results.
        
        Args:
            plan: The execution plan to run
        """
        start_time = time.time()
        print("\n2. Executing plan...")
        logger.info(f"Executing plan with {len(plan.steps)} steps")
        
        execution_result, error = await safe_execute_async(
            self.execution_manager.execute_plan,
            plan,
            error_message="Error executing plan",
            log_error=True
        )
        
        if error:
            print(f"\n{format_error_for_user(error)}")
            return
        
        # Check for errors in the result
        if hasattr(execution_result, 'error_type'):
            logger.error(f"Plan execution failed: {execution_result.message}")
            print(f"Error: {execution_result.message}")
            return
        
        # Calculate execution time
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Plan executed in {elapsed_ms}ms")
        
        # Display results
        self._display_execution_results(execution_result)
    
    def _display_execution_results(self, execution_result: Any) -> None:
        """
        Display the execution results in a user-friendly format.
        
        Args:
            execution_result: The result from the execution manager or error
        """
        # Handle BaseError objects explicitly
        if isinstance(execution_result, BaseError):
            print(f"\nError: {execution_result.message}")
            
            # Check for context info
            if hasattr(execution_result, 'context') and execution_result.context:
                if 'error_details' in execution_result.context:
                    print(f"Details: {execution_result.context['error_details']}")
                elif 'original_exception' in execution_result.context:
                    print(f"Details: {str(execution_result.context['original_exception'])}")
            
            # Special handling for "not_found" errors to make them more user-friendly
            if hasattr(execution_result, 'context') and execution_result.context and 'status' in execution_result.context and execution_result.context['status'] == 'not_found':
                print("\nNo matching records were found in Okta.")
            elif hasattr(execution_result, 'context') and execution_result.context and 'error_details' in execution_result.context and 'not found' in str(execution_result.context['error_details']).lower():
                print("\nNo matching records were found in Okta.")
            else:
                print("\nPlan execution failed.")
            return
        
        # Handle normal execution results
        # Display execution summary
        if hasattr(execution_result, 'status'):
            if execution_result.status == "success":
                print(f"\nPlan executed successfully!")
            else:
                print(f"\nPlan execution completed with warnings/issues.")
            
            # Show entities queried
            if hasattr(execution_result, 'entities_queried') and execution_result.entities_queried:
                print(f"Entities queried: {', '.join(execution_result.entities_queried)}")
            
            # Show warnings/errors if any
            if hasattr(execution_result, 'errors') and execution_result.errors:
                logger.warning(f"Plan completed with {len(execution_result.errors)} warnings/errors")
                if len(execution_result.errors) == 1:
                    print(f"Warning: {execution_result.errors[0].error}")
                else:
                    print(f"Warnings/Errors: {len(execution_result.errors)}")
        
        # Format and show the final result
        if hasattr(execution_result, 'final_result'):
            final_result = execution_result.final_result
        else:
            # Fallback if execution_result doesn't have expected structure
            final_result = execution_result
        
        print("\nResult:")
        print("-" * 60)
        if isinstance(final_result, (dict, list)):
            # Handle empty results
            if not final_result:
                print("No matching results found.")
            else:
                # Pretty-print JSON
                try:
                    print(json.dumps(final_result, indent=2, default=str))
                except Exception:
                    print(str(final_result))
        else:
            print(final_result)
        print("-" * 60)
    
    async def run(self) -> None:
        """Run the CLI interface main loop."""
        # Display welcome message
        print("\n==== OKTA REAL-TIME AI AGENT ====")
        print("Ask natural language questions about your Okta environment.")
        print("Type 'exit' or 'quit' to exit.")
        print("================================\n")
        
        # Check if initialization worked
        if not await self.initialize():
            return
        
        # Show current Okta org
        print(f"Using Okta org: {settings.OKTA_CLIENT_ORGURL}")
        print(f"API token present: {'Yes' if settings.OKTA_API_TOKEN else 'No'}")
        
        # Process queries until exit
        while True:
            try:
                # Get query from user
                query = input("\nEnter your query (or 'exit' to quit): ")
                
                # Check for exit
                if query.lower() in ('exit', 'quit'):
                    print("Exiting. Goodbye!")
                    break
                    
                # Skip empty queries
                if not query.strip():
                    continue
                
                # Process the query
                await self.process_query(query)
                
            except KeyboardInterrupt:
                print("\nExiting. Goodbye!")
                break
            except EOFError:
                print("\nInput stream closed. Exiting.")
                break


async def main():
    """Application entry point."""
    try:
        # Create and run the CLI
        cli = OktaRealtimeAgentCLI()
        await cli.run()
        
    except Exception as e:
        error = BaseError(
            message="Unhandled exception",
            original_exception=e,
            context={"location": "main"}
        )
        error.log()
        print(f"\n{format_error_for_user(error)}")
        print("Please check the logs for more information.")


if __name__ == "__main__":
    # Run the async main function
    try:
        logger.info("Starting Okta Realtime Agent CLI")
        asyncio.run(main())
        logger.info("Okta Realtime Agent CLI terminated normally")
    except KeyboardInterrupt:
        logger.info("Application terminated by keyboard interrupt")
        print("\nExiting. Goodbye!")
    except Exception as e:
        error = BaseError(
            message="Fatal error",
            original_exception=e,
            context={"location": "script entry point"}
        )
        error.log()
        print(f"\nFatal error: {format_error_for_user(error)}")
        print(f"Details: {traceback.format_exc()}")
        sys.exit(1)