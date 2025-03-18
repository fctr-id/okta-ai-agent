#!/usr/bin/env python3
"""
Okta Code Tester

A simple utility to test Okta SDK code snippets extracted from AI responses.

Usage:
  python okta_code_tester.py                  # Interactive mode
  python okta_code_tester.py "code here"      # Executes the provided code
  python okta_code_tester.py -f response.txt  # Extracts code from file
"""

import asyncio
import json
import sys
import textwrap
import re
import logging
from pathlib import Path

# Add parent directory to path to find modules
sys.path.append(str(Path(__file__).parent.parent))

# Import from your project
from src.config.settings import settings
from okta.client import Client as OktaClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def extract_code(text):
    """Extract code from AI response that might contain XML tags, JSON or markdown."""
    code = None
    description = None
    
    # Extract description if available
    desc_match = re.search(r'<DESCRIPTION>(.*?)</DESCRIPTION>', text, re.DOTALL)
    if desc_match:
        description = desc_match.group(1).strip()
    
    # Extract code - check for CODE tags first
    code_match = re.search(r'<CODE>(.*?)</CODE>', text, re.DOTALL)
    if code_match:
        code = code_match.group(1).strip()
    
    # If no code found, try other formats
    if not code:
        # Try JSON in code blocks
        json_match = re.search(r'```json\s*(.*?)```', text, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(1).strip()
                data = json.loads(json_str)
                if 'code' in data:
                    code = data['code']
            except Exception as e:
                logger.debug(f"Failed to parse JSON: {e}")
        
        # Try raw JSON
        elif text.strip().startswith('{') and text.strip().endswith('}'):
            try:
                data = json.loads(text.strip())
                if 'code' in data:
                    code = data['code']
            except Exception as e:
                logger.debug(f"Failed to parse JSON: {e}")
        
        # Try markdown code blocks
        elif "```python" in text:
            code = text.split("```python")[1].split("```")[0].strip()
        elif "```" in text:
            code = text.split("```")[1].split("```")[0].strip()
        else:
            # Just use the whole text as code
            code = text.strip()
    
    return code, description

async def test_okta_code(code):
    """Execute the code and return the results."""
    print("\n=== Okta Code Tester ===")
    print(f"Using Okta org: {settings.OKTA_CLIENT_ORGURL}")
    
    # Initialize Okta client
    config = {
        'orgUrl': settings.OKTA_CLIENT_ORGURL,
        'token': settings.OKTA_API_TOKEN
    }
    client = OktaClient(config)
    
    # Create namespace for execution
    namespace = {
        'client': client,
        'okta_client': client,  # Add this for compatibility with examples
        'asyncio': asyncio,
        'json': json,
        'print': print  # Allow print statements in code
    }
    
    # Fix common issues in code
    fixed_code = code
    if 'okta_client.list_users' in code:
        print("Note: Converting okta_client to client for compatibility")
    
    # Wrap the code in an async function
    wrapped_code = f"""
async def _execute_code():
    # Make context variables available
    result = None
    
    # Execute the provided code
{textwrap.indent(fixed_code, '    ')}
    
    # Return all local variables
    return locals()
"""
    
    print("\n--- Code to Execute ---")
    print(fixed_code)
    print("----------------------")
    
    try:
        # Execute the code
        exec(wrapped_code, namespace)
        local_vars = await namespace['_execute_code']()
        
        # Filter out system variables
        results = {}
        for name, value in local_vars.items():
            if not name.startswith('_') and name not in ['client', 'okta_client', 'asyncio', 'json']:
                results[name] = value
        
        print("\n--- Execution Results ---")
        for name, value in results.items():
            print(f"\n{name}:")
            
            # Special handling for Okta response tuples
            if isinstance(value, tuple) and len(value) == 3:
                data, resp, err = value
                print("-- OKTA RESPONSE --")
                print(f"Data: {type(data)}")
                if hasattr(data, '__len__'):
                    print(f"Count: {len(data) if data else 0}")
                
                # Show first item or two if it's a collection
                if hasattr(data, '__iter__') and not isinstance(data, str):
                    try:
                        for i, item in enumerate(data):
                            if i >= 3:  # Only show up to 3 items
                                print("... more items ...")
                                break
                            print(f"\nItem {i+1}:")
                            if hasattr(item, 'to_dict'):
                                print(json.dumps(item.to_dict(), indent=2, default=str))
                            else:
                                print(item)
                    except:
                        pass
                elif hasattr(data, 'to_dict'):
                    # Single object with to_dict method
                    print("\nObject data:")
                    print(json.dumps(data.to_dict(), indent=2, default=str))
                
                if err:
                    print(f"\nError: {err}")
            else:
                try:
                    if hasattr(value, 'to_dict'):
                        # Convert Okta objects to dict for display
                        print(json.dumps(value.to_dict(), indent=2, default=str))
                    else:
                        # Try regular JSON serialization
                        print(json.dumps(value, indent=2, default=str))
                except:
                    # Fall back to regular print
                    print(value)
        
        return results
        
    except Exception as e:
        print(f"\nError executing code: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

async def interactive_mode():
    """Run in interactive mode where you can paste multiple code snippets."""
    while True:
        print("\n==== Okta Code Tester (Interactive Mode) ====")
        print("Paste AI response or code snippet (blank line to execute, 'exit' to quit):")
        
        lines = []
        while True:
            line = input()
            if line.strip().lower() == 'exit':
                return
            if not line.strip():
                break
            lines.append(line)
        
        if not lines:
            continue
            
        text = '\n'.join(lines)
        
        # Extract code and description
        code, description = extract_code(text)
        
        print("\nExtracted code:")
        if description:
            print(f"Description: {description}")
        print("-" * 60)
        print(code)
        print("-" * 60)
        
        confirm = input("\nExecute this code? (y/n): ")
        if confirm.lower() == 'y':
            await test_okta_code(code)

async def main():
    # Parse command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '-f':
            # Read from file
            if len(sys.argv) < 3:
                print("Error: No file specified")
                print("Usage: python okta_code_tester.py -f filename")
                return
                
            try:
                with open(sys.argv[2], 'r') as f:
                    text = f.read()
                    
                code = extract_code(text)
                print("\nExtracted code from file:")
                print(code)
                
                confirm = input("\nExecute this code? (y/n): ")
                if confirm.lower() == 'y':
                    await test_okta_code(code)
            except Exception as e:
                print(f"Error: {str(e)}")
        
        elif sys.argv[1] == '-i' or sys.argv[1] == '--interactive':
            # Interactive mode
            await interactive_mode()
        
        else:
            # Use the command line argument directly as code
            code = sys.argv[1]
            print("\nCode from command line:")
            print(code)
            
            confirm = input("\nExecute this code? (y/n): ")
            if confirm.lower() == 'y':
                await test_okta_code(code)
    else:
        # No arguments - interactive mode
        await interactive_mode()

if __name__ == "__main__":
    asyncio.run(main())