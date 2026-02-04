#!/usr/bin/env python3
"""
CLI Agent for Okta AI Agent v2.0
Uses the Multi-Agent Orchestrator for deterministic results.
"""

import asyncio
import sys
import os
import json
import argparse
import csv
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Setup project paths
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Change to project root directory (ensures relative paths work from any location)
os.chdir(project_root)

# Load .env file from project root (allows running from any directory)
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    print(f"Warning: .env file not found at {env_path}")

from src.config.settings import settings
from src.core.agents.orchestrator import execute_multi_agent_query
from src.core.okta.client import OktaClient
from src.utils.logging import get_logger, set_correlation_id, generate_correlation_id

logger = get_logger("cli_agent")

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def parse_script_output(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse JSON results from script output (same logic as backend)"""
    try:
        lines = stdout.split('\n')
        json_lines = []
        in_json = False
        
        for line in lines:
            if line.strip() == "QUERY RESULTS":
                in_json = True
                continue
            elif line.strip().startswith("====") and in_json and json_lines:
                break
            elif in_json and line.strip() and not line.strip().startswith("===="):
                json_lines.append(line)
        
        if json_lines:
            json_text = '\n'.join(json_lines)
            parsed_output = json.loads(json_text)
            
            # Support both old format (array) and new format (object with data/headers)
            if isinstance(parsed_output, list):
                return {
                    "display_type": "table",
                    "data": parsed_output,
                    "count": len(parsed_output)
                }
            elif isinstance(parsed_output, dict):
                return parsed_output
            
    except Exception as e:
        logger.warning(f"Failed to parse script output: {e}")
        return None
    
    return None

def save_results_to_csv(results_data: Dict[str, Any], query: str, correlation_id: str) -> Optional[Path]:
    """Save results to CSV file in logs/cli-results/"""
    try:
        # Create output directory
        output_dir = project_root / "logs" / "tako-cli-results"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # Sanitize query for filename (max 50 chars, remove special chars)
        safe_query = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in query)
        safe_query = safe_query[:50].strip().replace(' ', '_')
        filename = f"{safe_query}_{timestamp}.csv"
        output_path = output_dir / filename
        
        # Extract data array
        data = results_data.get("data", [])
        if not data:
            logger.warning("No data to save to CSV")
            return None
        
        # Write CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            # Get headers from first row
            if isinstance(data[0], dict):
                fieldnames = list(data[0].keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(csvfile)
                writer.writerows(data)
        
        logger.info(f"Results saved to {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")
        return None

async def execute_generated_script(script_code: str, correlation_id: str) -> Optional[Dict[str, Any]]:
    """Execute the generated Python script and return parsed results"""
    try:
        # Save script to tako-cli-scripts folder
        script_dir = project_root / "logs" / "tako-cli-scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"cli_execution_{correlation_id}.py"
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_code)
        
        logger.info(f"Saved script to {script_path}")
        
        # Detect Python executable (prefer venv)
        venv_python = project_root / "venv" / "Scripts" / "python.exe"
        python_exe = str(venv_python) if venv_python.exists() else "python"
        
        # Execute script
        logger.info(f"Executing script with {python_exe}")
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",
            script_path.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_dir),
            limit=1024*1024
        )
        
        # Wait for completion
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace')
            logger.error(f"Script execution failed: {error_msg}")
            print(f"{Colors.FAIL}Script execution failed:{Colors.ENDC}")
            print(error_msg)
            return None
        
        # Parse output
        stdout_str = stdout.decode('utf-8', errors='replace')
        results = parse_script_output(stdout_str)
        
        if not results:
            logger.warning("Failed to parse script output")
            print(f"{Colors.WARNING}Warning: Could not parse script output{Colors.ENDC}")
            return None
        
        return results
        
    except Exception as e:
        logger.error(f"Script execution error: {e}")
        print(f"{Colors.FAIL}Error executing script: {e}{Colors.ENDC}")
        return None


async def event_callback(event_type: str, event_data: Dict[str, Any]):
    """Handle events from the orchestrator"""
    if event_type == "step_start":
        print(f"{Colors.OKBLUE}[{event_data.get('title', 'Step')}] {event_data.get('text', '')}{Colors.ENDC}")
    elif event_type == "progress":
        print(f"  {Colors.OKCYAN}â†ª {event_data.get('message', '')}{Colors.ENDC}")
    elif event_type == "tool_call":
        print(f"  {Colors.OKGREEN}ðŸ›  Using tool: {event_data.get('tool_name')}{Colors.ENDC}")

async def run_query(query: str, script_only: bool = False):
    """Execute a single query through the orchestrator"""
    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)
    
    artifacts_dir = project_root / "logs"
    artifacts_dir.mkdir(exist_ok=True)
    artifacts_file = artifacts_dir / f"cli_artifacts_{correlation_id}.json"
    
    # Initialize artifacts file
    with open(artifacts_file, 'w', encoding='utf-8') as f:
        json.dump([], f)
        
    okta_client = OktaClient()
    
    def check_cancelled():
        return False

    print(f"\n{Colors.BOLD}Query:{Colors.ENDC} {query}")
    print("-" * 50)

    result = await execute_multi_agent_query(
        user_query=query,
        correlation_id=correlation_id,
        artifacts_file=artifacts_file,
        okta_client=okta_client,
        cancellation_check=check_cancelled,
        event_callback=event_callback,
        cli_mode=True
    )

    if not result.success:
        print(f"\n{Colors.FAIL}Error: {result.error}{Colors.ENDC}")
        return

    # Handle special tools (summaries, modifications, etc.)
    if result.is_special_tool:
        print(f"\n{Colors.BOLD}Result:{Colors.ENDC}\n")
        print(result.script_code)  # Contains the summary/result
        logger.info(f"Special tool result returned for query: {query}")
        return

    # Script-only mode: save script to file
    if script_only:
        # Save to tako-cli-scripts folder
        script_dir = project_root / "logs" / "tako-cli-scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_query = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in query)
        safe_query = safe_query[:50].strip().replace(' ', '_')
        script_filename = f"{safe_query}_{timestamp}.py"
        script_path = script_dir / script_filename
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(result.script_code)
        
        print(f"\n{Colors.OKGREEN}Script saved to:{Colors.ENDC} {script_path}")
        logger.info(f"Script generated for query: {query}")
        return

    # Full mode: execute the script and save results
    print(f"\n{Colors.OKGREEN}Discovery complete. Executing script...{Colors.ENDC}")
    
    results_data = await execute_generated_script(result.script_code, correlation_id)
    
    if not results_data:
        print(f"\n{Colors.WARNING}No results returned from script execution{Colors.ENDC}")
        return
    
    # Display results summary
    record_count = results_data.get("count", 0)
    display_type = results_data.get("display_type", "table")
    print(f"\n{Colors.OKGREEN}Execution complete!{Colors.ENDC}")
    print(f"  Records returned: {record_count}")
    print(f"  Display type: {display_type}")
    
    # Save to CSV
    csv_path = save_results_to_csv(results_data, query, correlation_id)
    if csv_path:
        print(f"\n{Colors.BOLD}Results saved to:{Colors.ENDC} {csv_path}")
    
    # Show first few rows as preview
    data = results_data.get("data", [])
    if data and isinstance(data, list) and len(data) > 0:
        print(f"\n{Colors.BOLD}Preview (first 3 rows):{Colors.ENDC}")
        for i, row in enumerate(data[:3]):
            print(f"  {i+1}. {row}")


async def main():
    parser = argparse.ArgumentParser(description="Tako CLI Agent v2.0")
    parser.add_argument("query", nargs="?", help="The query to execute")
    parser.add_argument("--scriptonly", action="store_true", help="Only generate the script, do not execute")
    parser.add_argument("-i", "--interactive", action="store_true", help="Run in interactive mode")
    
    args = parser.parse_args()
    
    if args.interactive:
        print(f"{Colors.HEADER}{Colors.BOLD}Tako CLI Agent Interactive Mode{Colors.ENDC}")
        print("Type 'exit' or 'quit' to end session.")
        while True:
            try:
                query = input(f"\n{Colors.OKBLUE}Query > {Colors.ENDC}").strip()
                if query.lower() in ["exit", "quit"]:
                    break
                if not query:
                    continue
                await run_query(query, args.scriptonly)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
    elif args.query:
        await run_query(args.query, args.scriptonly)
    else:
        parser.print_help()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
