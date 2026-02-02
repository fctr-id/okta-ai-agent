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
from pathlib import Path
from typing import Dict, Any, Optional

# Setup project paths
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

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
        event_callback=event_callback
    )

    if not result.success:
        print(f"\n{Colors.FAIL}Error: {result.error}{Colors.ENDC}")
        return

    if script_only:
        print(f"\n{Colors.HEADER}--- GENERATED SCRIPT ---{Colors.ENDC}")
        print(result.script_code)
        print(f"{Colors.HEADER}------------------------{Colors.ENDC}")
        return

    # If not script_only, we need to execute the script
    # For the CLI, we can either execute it here or just show the result if it was a special tool
    if result.is_special_tool:
        print(f"\n{Colors.BOLD}Result:{Colors.ENDC}\n")
        print(result.script_code) # Contains the summary
    else:
        print(f"\n{Colors.OKGREEN}Discovery complete. Executing script...{Colors.ENDC}")
        # In a real CLI we might want to actually run the script and show results
        # For now, we follow the --scriptonly requirement and parity
        print(f"\n{Colors.HEADER}Script Code:{Colors.ENDC}\n")
        print(result.script_code)
        print("\n(Script execution in CLI is under development. Use the Web UI for full results visualization.)")

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
