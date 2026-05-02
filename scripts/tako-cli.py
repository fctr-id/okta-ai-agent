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
import shutil
import re
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
from src.data.schemas.runtime_storage import (
    create_runtime_turn_paths,
    prepare_runtime_script_code,
    update_turn_metadata,
    write_turn_summary,
)
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


def extract_markdown_content(results_data: Dict[str, Any]) -> str:
    """Return markdown/text content from parsed script results."""
    for key in ("content", "markdown", "message", "response_text", "text"):
        value = results_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def save_results_to_csv(results_data: Dict[str, Any], date_str: str, output_dir: Optional[Path] = None) -> Optional[Path]:
    """Save results to CSV file in logs/tako-cli-results/"""
    try:
        # Create output directory
        output_dir = output_dir or project_root / "logs" / "tako-cli-results"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate standardized filename
        filename = f"tako-csv-results-{date_str}.csv"
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


def copy_base_client_if_needed(prepared_code: str, target_dir: Path) -> None:
    """Copy the standalone Okta API client next to generated scripts when required."""
    if "from base_okta_api_client import" not in prepared_code and "import base_okta_api_client" not in prepared_code:
        return

    base_client_dest = target_dir / "base_okta_api_client.py"
    candidate_sources = [
        project_root / "generated_scripts" / "base_okta_api_client.py",
        project_root / "src" / "core" / "okta" / "client" / "base_okta_api_client.py",
    ]

    destination_path = base_client_dest.resolve()
    for candidate in candidate_sources:
        if not candidate.exists():
            continue

        try:
            if candidate.resolve() == destination_path:
                continue
        except FileNotFoundError:
            continue

        shutil.copy2(candidate, base_client_dest)
        logger.info(f"Copied base_okta_api_client.py to {target_dir}")
        return

    if base_client_dest.exists():
        logger.debug(f"base_okta_api_client.py already available in {target_dir}")
    else:
        logger.warning("base_okta_api_client.py not found in expected locations")

async def execute_generated_script(
    script_code: str,
    date_str: str,
    query: str,
) -> Optional[Dict[str, Any]]:
    """Execute the generated Python script and return parsed results"""
    script_path = None
    try:
        # Stage script for execution only. Durable storage keeps summaries/results, not every script.
        script_dir = project_root / "generated_scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"tako-cli-script-{date_str}.py"
        
        # Add query as comment at the top of the script
        commented_query = f"# Query: {query}\n# Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n\n"
        prepared_code = prepare_runtime_script_code(script_code)
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(commented_query + prepared_code)
        
        logger.info(f"Saved script to {script_path}")

        copy_base_client_if_needed(prepared_code, script_dir)
        
        # Detect Python executable (prefer venv)
        venv_python = project_root / "venv" / "Scripts" / "python.exe"
        python_exe = str(venv_python) if venv_python.exists() else "python"
        
        # Execute script
        logger.info(f"Executing script with {python_exe}")
        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",
            str(script_path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_root),
            limit=1024*1024
        )
        
        # Wait for completion
        stdout, stderr = await proc.communicate()
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        
        if proc.returncode != 0:
            error_msg = stderr_str
            logger.error(f"Script execution failed: {error_msg}")
            print(f"{Colors.FAIL}Script execution failed:{Colors.ENDC}")
            print(error_msg)
            return None
        
        # Parse output
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
    finally:
        try:
            if script_path and script_path.exists():
                script_path.unlink()
        except Exception:
            logger.debug(f"Failed to clean up temp script: {script_path}")


def clean_cli_text(value: Any) -> str:
    """Remove emoji and other non-ASCII display glyphs from CLI output."""
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', '', text)
    text = text.encode('ascii', errors='ignore').decode('ascii')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def event_callback(event_type: str, event_data: Dict[str, Any]):
    """Handle events from the orchestrator"""
    if event_type == "step_start":
        title = clean_cli_text(event_data.get('title', 'Step')) or 'Step'
        text = clean_cli_text(event_data.get('text', ''))
        print(f"{Colors.OKBLUE}[{title}] {text}{Colors.ENDC}")
    elif event_type == "progress":
        message = clean_cli_text(event_data.get('message', ''))
        print(f"  {Colors.OKCYAN}-> {message}{Colors.ENDC}")
    elif event_type == "tool_call":
        tool_name = clean_cli_text(event_data.get('tool_name') or event_data.get('name') or 'unknown_tool')
        print(f"  {Colors.OKGREEN}Using tool: {tool_name}{Colors.ENDC}")

async def run_query(query: str, script_only: bool = False, session_id: Optional[str] = None):
    """Execute a single query through the orchestrator"""
    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)
    cli_user = os.getenv("USERNAME") or os.getenv("USER") or "cli"
    
    # Generate standardized filename with date and time (no query, no random number)
    # Format: tako-cli-script-MM-DD-YYYY-HH-MM or tako-csv-results-MM-DD-YYYY-HH-MM
    date_str = datetime.now().strftime("%m-%d-%Y-%H-%M")
    
    runtime_paths = create_runtime_turn_paths(
        user_id=f"cli-{cli_user}",
        session_id=session_id or correlation_id,
        run_id=correlation_id,
    )
    artifacts_file = runtime_paths.artifacts_file
    update_turn_metadata(runtime_paths, status="executing", user_query=query)
        
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
        update_turn_metadata(runtime_paths, status="error", error=result.error, completed_at=datetime.now().isoformat())
        return

    if result.no_data_found:
        print(f"\n{Colors.WARNING}No results found.{Colors.ENDC}")
        print(result.user_message or "Your query completed successfully, but no matching data was found.")
        write_turn_summary(runtime_paths, {
            "status": "completed",
            "user_query": query,
            "final_response_summary": result.user_message or "No matching data was found.",
            "display_type": "markdown",
            "artifact_file": artifacts_file.as_posix(),
            "outcome": result.outcome_metadata(),
        })
        update_turn_metadata(runtime_paths, status="completed", completed_at=datetime.now().isoformat())
        return

    if result.is_degraded_success:
        print(f"\n{Colors.WARNING}Partial result:{Colors.ENDC} {result.user_message or result.outcome_reason}")

    # Handle special tools (summaries, modifications, etc.)
    if result.is_special_tool:
        print(f"\n{Colors.BOLD}Result:{Colors.ENDC}\n")
        print(result.script_code)  # Contains the summary/result
        logger.info(f"Special tool result returned for query: {query}")
        write_turn_summary(runtime_paths, {
            "status": "completed",
            "user_query": query,
            "final_response_summary": result.script_code or "Special tool result",
            "display_type": result.display_type or "markdown",
            "artifact_file": artifacts_file.as_posix(),
            "is_special_tool": True,
            "outcome": result.outcome_metadata(),
        })
        update_turn_metadata(runtime_paths, status="completed", completed_at=datetime.now().isoformat())
        return

    if not result.script_code:
        print(f"\n{Colors.FAIL}Error: No executable script was generated for this query.{Colors.ENDC}")
        logger.error(f"No script generated for query: {query}")
        update_turn_metadata(runtime_paths, status="error", error="No executable script generated", completed_at=datetime.now().isoformat())
        return

    # Script-only mode: save script to file
    if script_only:
        # Save to tako-cli-scripts folder
        script_dir = project_root / "logs" / "tako-cli-scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        
        script_filename = f"tako-cli-script-{date_str}.py"
        script_path = script_dir / script_filename
        
        # Add query as comment at the top of the script
        commented_query = f"# Query: {query}\n# Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n\n"
        prepared_code = prepare_runtime_script_code(result.script_code)
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(commented_query + prepared_code)

        copy_base_client_if_needed(prepared_code, script_dir)
        
        print(f"\n{Colors.OKGREEN}Script saved to:{Colors.ENDC} {script_path}")
        logger.info(f"Script generated for query: {query}")
        write_turn_summary(runtime_paths, {
            "status": "script_generated",
            "user_query": query,
            "final_response_summary": "Script generated without execution.",
            "artifact_file": artifacts_file.as_posix(),
            "script_path": script_path.as_posix(),
            "outcome": result.outcome_metadata(),
        })
        update_turn_metadata(runtime_paths, status="script_generated", completed_at=datetime.now().isoformat())
        return

    # Full mode: execute the script and save results
    print(f"\n{Colors.OKGREEN}Discovery complete. Executing script...{Colors.ENDC}")
    
    results_data = await execute_generated_script(result.script_code, date_str, query)
    
    if not results_data:
        print(f"\n{Colors.WARNING}No results returned from script execution{Colors.ENDC}")
        update_turn_metadata(runtime_paths, status="error", error="No results returned from script execution", completed_at=datetime.now().isoformat())
        return
    
    # Display results summary
    record_count = results_data.get("count", 0)
    display_type = results_data.get("display_type", "table")
    print(f"\n{Colors.OKGREEN}Execution complete!{Colors.ENDC}")
    print(f"  Records returned: {record_count}")
    print(f"  Display type: {display_type}")

    csv_path = None
    markdown_content = ""

    if display_type == "markdown":
        markdown_content = extract_markdown_content(results_data)
        if markdown_content:
            print(f"\n{Colors.BOLD}Response:{Colors.ENDC}\n")
            print(markdown_content)
        else:
            print(f"\n{Colors.WARNING}Warning: Markdown response had no content field.{Colors.ENDC}")
    else:
        # Save to CSV for tabular outputs only
        csv_path = save_results_to_csv(results_data, date_str, output_dir=runtime_paths.results_dir)
        if csv_path:
            print(f"\n{Colors.BOLD}Results saved to:{Colors.ENDC} {csv_path}")

        # Show first few rows as preview
        data = results_data.get("data", [])
        if data and isinstance(data, list) and len(data) > 0:
            print(f"\n{Colors.BOLD}Preview (first 3 rows):{Colors.ENDC}")
            for i, row in enumerate(data[:3]):
                print(f"  {i+1}. {row}")

    final_response_summary = markdown_content or f"Found {record_count} results"

    write_turn_summary(runtime_paths, {
        "status": "completed",
        "user_query": query,
        "final_response_summary": final_response_summary,
        "display_type": display_type,
        "result_count": record_count,
        "artifact_file": artifacts_file.as_posix(),
        "csv_path": csv_path.as_posix() if csv_path else None,
        "outcome": result.outcome_metadata(),
        "token_usage": {
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "total_tokens": result.total_tokens,
            "requests": result.total_requests,
        },
    })
    update_turn_metadata(runtime_paths, status="completed", completed_at=datetime.now().isoformat())


async def main():
    parser = argparse.ArgumentParser(description="Tako CLI Agent v2.0")
    parser.add_argument("query", nargs="?", help="The query to execute")
    parser.add_argument("--scriptonly", action="store_true", help="Only generate the script, do not execute")
    parser.add_argument("--session-id", help="Optional session id for grouping CLI turns")
    parser.add_argument("-i", "--interactive", action="store_true", help="Run in interactive mode")
    
    args = parser.parse_args()
    
    if args.interactive:
        print(f"{Colors.HEADER}{Colors.BOLD}Tako CLI Agent Interactive Mode{Colors.ENDC}")
        print("Type 'exit' or 'quit' to end session.")
        interactive_session_id = args.session_id or generate_correlation_id("cli-session")
        while True:
            try:
                query = input(f"\n{Colors.OKBLUE}Query > {Colors.ENDC}").strip()
                if query.lower() in ["exit", "quit"]:
                    break
                if not query:
                    continue
                await run_query(query, args.scriptonly, session_id=interactive_session_id)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
    elif args.query:
        await run_query(args.query, args.scriptonly, session_id=args.session_id)
    else:
        parser.print_help()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
