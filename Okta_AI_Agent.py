from src.core.helpers.okta_pre_reasoning_agent import reasoning_agent
from src.core.helpers.okta_generate_sql import sql_agent, extract_json_from_text
from src.okta_db_sync.db.operations import DatabaseOperations
from src.config.settings import settings
from typing import Dict, List, Any
from sqlalchemy import text
import asyncio
import json, os, sys
from pathlib import Path
import csv
import pytz
from io import StringIO
from dotenv import load_dotenv
from datetime import datetime
from src.utils.logging import logger

load_dotenv(override=True)

src_path = Path(__file__).parent / "src"
sys.path.append(str(src_path))

def check_virtual_environment() -> bool:
    """Check if running in the correct virtual environment"""
    venv_path = Path(__file__).parent / "venv"
    current_venv = Path(sys.prefix)
    
    # Check if running in any venv
    is_in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    # Check if it's our specific venv
    is_correct_venv = current_venv.resolve() == venv_path.resolve()
    
    return is_in_venv and is_correct_venv

def validate_environment():
    """Validate the running environment"""
    if not check_virtual_environment():
        print("\n⚠️ Error: Virtual environment not activated!")
        print("\nPlease activate your virtual environment:")
        print("1. Open terminal in project root")
        print("2. Run: ")
        if sys.platform == "win32":
            print("   .\\venv\\Scripts\\activate")
        else:
            print("   source venv/bin/activate")
        print("\nThen run this script again.")
        sys.exit(1)
    
    logger.info("Virtual environment validated")
    
# Validate environment
validate_environment()  


# Add after existing imports
RESULTS_DIR = Path(__file__).parent / "results"

# Add this function after SQLExecutor class
def save_results_to_csv(results: List[dict], filename: str):
    """Save query results to CSV file"""
    # Create results directory if it doesn't exist
    RESULTS_DIR.mkdir(exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_filename = RESULTS_DIR / f"{filename}_{timestamp}.csv"
    
    try:
        with open(full_filename, 'w', newline='') as csvfile:
            if results:
                writer = csv.DictWriter(csvfile, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)
                logger.info(f"Results saved to: {full_filename}")
                return str(full_filename)
    except Exception as e:
        logger.error(f"Error saving results to CSV: {str(e)}")
        raise  
    
  

# Add configuration for reasoning

class SQLExecutor:
    def __init__(self):
        self.db = DatabaseOperations()
        logger.info("Initialized SQLExecutor")  # Log initialization
    
    @staticmethod
    async def validate_sql(sql: str) -> bool:
        """Validate SQL query for safety"""
        # Check if query starts with SELECT
        if not sql.upper().strip().startswith('SELECT'):
            logger.warning(f"Non-SELECT query attempted: {sql}")
            return False
            
        # Check for dangerous operations
        dangerous_ops = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'TRUNCATE', 'ALTER']
        for op in dangerous_ops:
            if f" {op} " in sql.upper():
                logger.warning(f"Dangerous operation {op} found in query: {sql}")
                return False
        
        logger.debug("SQL validation passed")
        return True
    
    async def execute_query(self, sql: str) -> Dict[str, Any]:
        """Execute SQL query and return formatted results"""
        try:
            if not await self.validate_sql(sql):
                logger.error("Invalid SQL query attempted")
                return {"error": "This query type is not allowed"}
                
            async with self.db.get_session() as session:
                logger.debug(f"Executing SQL: {sql}")
                sql_text = text(sql)
                query_result = await session.execute(sql_text)
                rows = query_result.fetchall()
                
                columns = query_result.keys()
                data = [dict(zip(columns, row)) for row in rows]
                
                #logger.info(f"Query executed successfully. Found {len(data)} records")
                return {
                    "results": data,
                    "count": len(data)
                }
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}", exc_info=True)
            return {"error": str(e)}
        
def get_local_timezone():
    """Get the local timezone name"""
    return datetime.now().astimezone().tzname()
        
from datetime import datetime
import pytz
from zoneinfo import ZoneInfo

async def get_last_sync_info(executor: SQLExecutor) -> str:
    """Get last successful sync time for users entity in local timezone"""
    sql = """
    SELECT 
        sync_end_time as last_sync,
        records_processed
    FROM sync_history 
    WHERE status = 'SUCCESS'
    AND entity_type = 'User'
    ORDER BY sync_end_time DESC
    LIMIT 1
    """
    try:
        result = await executor.execute_query(sql)
        if result and result.get("results") and len(result["results"]) > 0:
            sync_info = result["results"][0]
            
            # Convert UTC timestamp to local time
            utc_dt = datetime.fromisoformat(str(sync_info['last_sync']))
            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
            
            # Get local timezone
            local_tz = datetime.now().astimezone().tzinfo
            local_time = utc_dt.astimezone(local_tz)
            
            # Format with 12-hour clock
            formatted_time = local_time.strftime("%Y-%m-%d %I:%M:%S %p %Z")
            return f"\n🔄 Last Users Sync: {formatted_time} ({sync_info['records_processed']} records)"
        return "\n🔄 No user sync history available"
    except Exception as e:
        logger.error(f"Error fetching users sync history: {str(e)}")
        return "\n🔄 Unable to fetch sync information"
    

### Reasoning Agent Integration        
        
async def process_with_reasoning(question: str) -> Dict[str, str]:
    """Process question through reasoning agent first"""
    try:
        logger.debug("Running reasoning agent")
        response = await reasoning_agent.run(question)
        logger.debug("Reasoning agent response received" + str(response.output))
        expanded = json.loads(str(response.output))
        
        logger.info("Original question: " + question)
        logger.info("Expanded query: " + expanded["expanded_query"])
        logger.debug("Reasoning: " + expanded["explanation"])
        
        return {
            "query": expanded["expanded_query"],
            "explanation": expanded["explanation"]
        }
    except Exception as e:
        logger.error(f"Reasoning agent failed: {str(e)}", exc_info=True)
        return {
            "query": question,  # Fallback to original question
            "explanation": f"Reasoning failed: {str(e)}"
        }

      
DISPLAY_LIMIT = 20
USE_PRE_REASONING = os.getenv('USE_PRE_REASONING', 'false').lower() == 'true'
#print(f"Using Pre-Reasoning: {USE_PRE_REASONING}")

class Colors:
    BLUE_BG = '\033[44m'
    GREEN_BG = '\033[42m'
    MAGENTA_BG = '\033[45m'
    RESET = '\033[0m'
    
    
async def main():
    executor = SQLExecutor()
    logger.info(f"Starting Okta Query Assistant (Reasoning: {'Enabled' if USE_PRE_REASONING else 'Disabled'}) Provider: {os.getenv('AI_PROVIDER')}")
    print("\nWelcome to Okta Query Assistant!")
    print(f"{Colors.GREEN_BG}Reasoning Agent: {Colors.RESET}{'Enabled' if USE_PRE_REASONING else 'Disabled'}")
    print("Type 'exit' to quit\n")
    
    while True:
        question = input("\nWhat would you like to know about your Okta data? > ")
        if question.lower() == 'exit':
            logger.info("User requested exit")
            break
            
        try:
            logger.debug(f"Processing question: {question}")
            output_format = 'json' if 'json' in question.lower() else 'csv'
            
            # Apply reasoning if enabled
            if USE_PRE_REASONING:
                reasoning_result = await process_with_reasoning(question)
                if not reasoning_result["query"].strip():
                    logger.info("Empty query from reasoning - cannot proceed")
                    print("\nCannot process query:")
                    print("-" * 40)
                    print(reasoning_result["explanation"])
                    print("-" * 40)
                    continue
                processed_question = reasoning_result["query"]
                # Add colored output for expanded query
                print(f"\n{Colors.BLUE_BG}Expanded Query:{Colors.RESET}")
                print(f"{processed_question}")
                logger.debug("Using processed question for SQL generation")
            else:
                processed_question = question
            
            # Generate SQL using the agent
            logger.debug("Generating SQL using agent")
            sql_response = await sql_agent.run(processed_question)
            result = extract_json_from_text(str(sql_response.output))
            
                        # Add colored output for generated SQL
            print(f"\n{Colors.GREEN_BG}Generated SQL:{Colors.RESET}")
            print(f"{result['sql']}")
            
            # Check if SQL is empty (invalid/unsupported query)
            if not result["sql"].strip():
                logger.info("Empty SQL received - query not supported")
                print("\nResponse:")
                print("-" * 40)
                print(result["explanation"])
                print("-" * 40)
                continue            
            
            # Execute the generated SQL
            logger.info(f"Executing generated SQL: {result['sql']}")
            query_result = await executor.execute_query(result["sql"])
            explanation = result["explanation"]
            logger.info(f"Query explanation: {explanation}")
            
            if "error" in query_result:
                logger.error(f"Query execution failed: {query_result['error']}")
                print(f"Error: {query_result['error']}")
            else:
                logger.info(f"Query executed successfully. Found {query_result['count']} records")
                
                if query_result["count"] > 0:
                    print(f"\nFound {query_result['count']} results")
                    print("-" * 40)
                    
                    # Handle results based on count
                    if query_result["count"] <= DISPLAY_LIMIT:
                        # Display small result sets in console
                        if output_format == 'json':
                            print(json.dumps(query_result["results"], indent=2))
                        else:
                            output = StringIO()
                            writer = csv.DictWriter(output, fieldnames=query_result["results"][0].keys())
                            writer.writeheader()
                            writer.writerows(query_result["results"])
                            print(output.getvalue())
                            
                        sync_info = await get_last_sync_info(executor)
                        print("\n" + "-" * 40)
                        print(sync_info)                              
                    else:
                        # Automatically save larger result sets
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"okta_ai_agent_results_{timestamp}.csv"
                            saved_file = save_results_to_csv(
                                query_result["results"], 
                                "okta_ai_agent_results"
                            )
                            print(f"\n📊 Found {query_result['count']} records")
                            print(f"{Colors.MAGENTA_BG}💾 Results automatically saved to:{Colors.RESET} {saved_file}")
                            print(f"\nFirst {DISPLAY_LIMIT} records preview:")
                            print("-" * 40)
                            
                            # Show preview of first few records
                            preview_data = query_result["results"][:DISPLAY_LIMIT]
                            if output_format == 'json':
                                print(json.dumps(preview_data, indent=2))
                            else:
                                output = StringIO()
                                writer = csv.DictWriter(output, fieldnames=preview_data[0].keys())
                                writer.writeheader()
                                writer.writerows(preview_data)
                                print(output.getvalue())
                                          
                            
                        except Exception as e:
                            logger.error(f"Error saving results: {str(e)}")
                            print(f"\n❌ Error saving results: {str(e)}")
                else:
                    print("No records found")                   
                         
        except Exception as e:
            logger.error(f"Error processing question: {str(e)}", exc_info=True)
            print(f"\nError: {str(e)}")
        
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())