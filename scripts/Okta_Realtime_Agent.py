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
import csv
from datetime import datetime
from pathlib import Path
import re

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


# Add these constants after other global variables
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
DISPLAY_LIMIT = 10  # Maximum number of results to display in console


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
        await self._execute_plan(plan_result.plan, query)
    
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
        
    def save_results_to_csv(self, results: List[dict], filename: str) -> str:
        """
        Save query results to CSV file.
        
        Args:
            results: List of dictionaries containing result data
            filename: Base filename without extension
            
        Returns:
            Path to saved CSV file
        """
        # Create results directory if it doesn't exist
        RESULTS_DIR.mkdir(exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        full_filename = RESULTS_DIR / f"{filename}_{timestamp}.csv"
        
        try:
            with open(full_filename, 'w', newline='', encoding='utf-8') as csvfile:
                if results:
                    writer = csv.DictWriter(csvfile, fieldnames=results[0].keys())
                    writer.writeheader()
                    writer.writerows(results)
                    logger.info(f"Results saved to: {full_filename}")
                    return str(full_filename)
            return str(full_filename)
        except Exception as e:
            logger.error(f"Error saving results to CSV: {str(e)}")
            raise
    
    # ADD NEW METHOD: Save Vue table format to CSV
    def _save_vue_table_to_csv(self, vue_table_data: Dict[str, Any]) -> str:
        """
        Save Vue.js compatible table data directly to CSV.
        
        Args:
            vue_table_data: Dictionary containing headers and items arrays
                
        Returns:
            Path to saved CSV file
        """
        # Create results directory if it doesn't exist
        RESULTS_DIR.mkdir(exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = RESULTS_DIR / f"okta_data_{timestamp}.csv"
        
        # Extract items and header information
        headers = vue_table_data.get("headers", [])
        items = vue_table_data.get("items", [])
        
        if not items:
            logger.warning("No items to save in CSV file")
            return str(csv_filename)
        
        try:
            # Extract column keys and titles from headers
            column_keys = [h.get("key") for h in headers]
            column_titles = [h.get("title") for h in headers]
            
            # If no column keys found, try extracting from first item
            if not column_keys and items:
                column_keys = list(items[0].keys())
                column_titles = column_keys  # Use keys as titles if not explicitly defined
            
            # Write to CSV
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                # Use column titles as the CSV header row
                writer = csv.writer(csvfile)
                writer.writerow(column_titles)
                
                # Write each item as a row, ensuring correct column order
                for item in items:
                    # Extract values using the column keys to ensure correct order
                    row = []
                    for key in column_keys:
                        value = item.get(key, '')
                        # Handle nested structures
                        if isinstance(value, (dict, list)):
                            value = json.dumps(value, default=str)
                        row.append(value)
                    writer.writerow(row)
                    
            logger.info(f"Table data saved to CSV: {csv_filename}")
            return str(csv_filename)
            
        except Exception as e:
            logger.error(f"Error saving table data to CSV: {str(e)}")
            return f"Error saving CSV: {str(e)}"
    
    async def _execute_plan(self, plan: ExecutionPlan, query: str) -> None:
        """
        Execute the created plan and display results.
        
        Args:
            plan: The execution plan to run
            query: The original user query for context
        """
        start_time = time.time()
        print("\n2. Executing plan...")
        logger.info(f"Executing plan with {len(plan.steps)} steps")
        
        execution_result, error = await safe_execute_async(
            self.execution_manager.execute_plan,
            plan,
            query,  # Pass the original query for results processing
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
            
            # Special handling for "not_found" errors
            if hasattr(execution_result, 'context') and execution_result.context:
                ctx = execution_result.context
                if ('status' in ctx and ctx['status'] == 'not_found') or \
                   ('error_details' in ctx and 'not found' in str(ctx['error_details']).lower()):
                    print("\nNo matching records were found in Okta.")
                else:
                    print("\nPlan execution failed.")
            return
        
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
        
        print("\nResult:")
        print("-" * 60)
        
        # Get the final result
        final_result = execution_result.final_result if hasattr(execution_result, 'final_result') else execution_result
        
        # Check if this is a dictionary in the Vue table format
        if isinstance(final_result, dict) and "headers" in final_result and "items" in final_result:
            saved_file = self._save_vue_table_to_csv(final_result)
            items = final_result.get("items", [])
            record_count = len(items)
            print(f"📊 Found {record_count} records in table format")
            print(f"💾 Data saved to: {saved_file}")
            return
        
        # Direct handling for AgentRunResult objects
        if hasattr(final_result, 'output'):
            output_content = final_result.output
            
            # Try to parse the output as JSON (either from markdown blocks or directly)
            json_content = self._extract_json(output_content)
            
            if json_content:
                # Process JSON content
                display_type = json_content.get('display_type', 'default')
                content = json_content.get('content', {})
                metadata = json_content.get('metadata', {})
                
                # Check for Vue table format
                if display_type == "table" and isinstance(content, dict) and "headers" in content and "items" in content:
                    saved_file = self._save_vue_table_to_csv(content)
                    items = content.get("items", [])
                    record_count = len(items)
                    print(f"📊 Found {record_count} records in table format")
                    print(f"💾 Data saved to: {saved_file}")
                    return
                
                # Handle other display types
                elif display_type == "markdown" and isinstance(content, str):
                    print(self._format_markdown_for_terminal(content))
                    return
                
                # Legacy table format
                elif display_type == "table" and isinstance(content, list):
                    columns = metadata.get("columns", [])
                    
                    # Convert to Vue format and save
                    headers = [{"key": col, "title": col, "align": "start", "sortable": True} for col in columns]
                    vue_data = {"headers": headers, "items": content}
                    
                    # Save as CSV
                    saved_file = self._save_vue_table_to_csv(vue_data)
                    record_count = len(content)
                    print(f"📊 Found {record_count} records in table format")
                    print(f"💾 Data saved to: {saved_file}")
                    return
                
                # Fall back to printing the JSON content
                print(json.dumps(json_content, indent=2, default=str))
                return
            else:
                # If we couldn't parse JSON, just print the output
                print(output_content)
                return
        
        # Handle empty results
        if not final_result:
            print("No matching results found.")
            return
        
        # Fallback handling for non-processed results
        display_type = execution_result.display_type if hasattr(execution_result, 'display_type') else "default"
        
        # Special handling for table type to save to CSV
        if display_type == "table" and isinstance(final_result, list) and final_result:
            # Try to get columns or extract them from first item
            display_hints = execution_result.display_hints if hasattr(execution_result, 'display_hints') else {}
            columns = display_hints.get("columns", [])
            
            if not columns and isinstance(final_result[0], dict):
                columns = list(final_result[0].keys())
            
            if columns:
                # Convert to Vue format and save
                headers = [{"key": col, "title": col, "align": "start", "sortable": True} for col in columns]
                vue_data = {"headers": headers, "items": final_result}
                
                saved_file = self._save_vue_table_to_csv(vue_data)
                record_count = len(final_result)
                print(f"📊 Found {record_count} records in table format")
                print(f"💾 Data saved to: {saved_file}")
                
                # Also print a preview
                if len(final_result) > DISPLAY_LIMIT:
                    print("\nPreview of first few records:")
                    self._print_table(final_result[:DISPLAY_LIMIT], columns)
                else:
                    self._print_table(final_result, columns)
                
                return
        
        # Default: just print as JSON
        try:
            print(json.dumps(final_result, indent=2, default=str))
        except:
            print(str(final_result))
    
    def _extract_json(self, text):
        """Extract JSON from text, handling markdown code blocks."""
        # First try to extract from markdown code blocks
        json_match = re.search(r'```json\s+(.*?)\s+```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass
        
        # Then try direct JSON parsing
        try:
            return json.loads(text)
        except:
            # Try cleaning markdown blocks
            cleaned = re.sub(r'```json\s+|\s+```', '', text)
            try:
                return json.loads(cleaned)
            except:
                return None

    def _format_markdown_for_terminal(self, markdown_text: str) -> str:
        """Format markdown text for better display in the terminal."""
        # Make headings stand out
        formatted = re.sub(r'^# (.+)$', r'\n\033[1;4m\1\033[0m', markdown_text, flags=re.MULTILINE)
        formatted = re.sub(r'^## (.+)$', r'\n\033[1m\1\033[0m', formatted, flags=re.MULTILINE)
        formatted = re.sub(r'^### (.+)$', r'\n\033[1m\1\033[0m', formatted, flags=re.MULTILINE)
        
        # Highlight bullet points
        formatted = re.sub(r'^- (.+)$', r'• \1', formatted, flags=re.MULTILINE)
        
        # Bold and italic formatting
        formatted = re.sub(r'\*\*(.+?)\*\*', r'\033[1m\1\033[0m', formatted)
        formatted = re.sub(r'\*(.+?)\*', r'\033[3m\1\033[0m', formatted)
        
        # Format code blocks
        formatted = re.sub(r'```.*?\n(.+?)```', r'\n--- Code ---\n\1\n-----------', formatted, flags=re.DOTALL)
        
        return formatted

    def _print_table(self, data: List[dict], columns: List[str]) -> None:
        """Print data as a formatted table."""
        # Filter columns to only include those that exist in the data
        if data and isinstance(data[0], dict):
            valid_columns = [col for col in columns if any(col in row for row in data)]
        else:
            valid_columns = []
        
        if not data or not valid_columns:
            print(json.dumps(data, indent=2, default=str))
            return
        
        # Calculate column widths
        widths = {col: max(len(str(col)), max(len(str(row.get(col, ''))) for row in data)) for col in valid_columns}
        
        # Print header
        header = " | ".join(str(col).ljust(widths[col]) for col in valid_columns)
        print(header)
        print("-" * len(header))
        
        # Print rows
        for row in data:
            # Convert all values to strings, handle nested objects
            formatted_row = {}
            for col in valid_columns:
                val = row.get(col, '')
                if isinstance(val, (dict, list)):
                    formatted_row[col] = "..." 
                elif val is None:
                    formatted_row[col] = ""
                else:
                    formatted_row[col] = str(val)
                    
            row_str = " | ".join(formatted_row[col].ljust(widths[col]) for col in valid_columns)
            print(row_str)

    def _print_table_preview(self, data: List[dict], columns: List[str]) -> None:
        """Print preview of data as a formatted table."""
        print(f"\nFirst {len(data)} records preview:")
        self._print_table(data, columns)
    
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
                query = input("\nEnter your query (or 'exit' to quit) \nNOTE: All names are case-sensitive. Match exact case of the entity name as in Okta: ")
                
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