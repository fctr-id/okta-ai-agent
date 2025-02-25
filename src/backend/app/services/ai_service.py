from typing import Dict, Any, AsyncGenerator
import json
from datetime import datetime
import pytz
from sqlalchemy import text
from src.core.helpers.okta_pre_reasoning_agent import expand_query
from src.core.helpers.okta_generate_sql import sql_agent, extract_json_from_text
from src.okta_db_sync.db.operations import DatabaseOperations
from src.utils.logging import logger

class SQLExecutor:
    def __init__(self):
        self.db = DatabaseOperations()
        logger.info("Initialized SQLExecutor")  # Log initialization
    
    @staticmethod
    async def validate_sql(sql: str) -> bool:
        """Validate SQL query for safety"""
        logger.debug(f"Validating SQL query: {sql}")
        
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
            logger.debug(f"Starting query execution: {sql}")
            
            if not await self.validate_sql(sql):
                logger.error("Invalid SQL query attempted")
                return {"error": "This query type is not allowed"}
                
            async with self.db.get_session() as session:
                logger.debug("Database session created")
                sql_text = text(sql)
                query_result = await session.execute(sql_text)
                rows = query_result.fetchall()
                
                columns = query_result.keys()
                data = [dict(zip(columns, row)) for row in rows]
                
                logger.info(f"Query executed successfully. Found {len(data)} records")
                return {
                    "results": data,
                    "count": len(data)
                }
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}", exc_info=True)
            return {"error": str(e)}

class AIService:
    @staticmethod
    async def get_last_sync_info(executor: SQLExecutor) -> str:
        """Get last successful sync time for users entity in local timezone"""
        logger.debug("Fetching last sync information")
        
        sql = """
        SELECT sync_end_time as last_sync
        FROM sync_history 
        WHERE status = 'SUCCESS'
        AND entity_type = 'User'
        ORDER BY sync_end_time DESC
        LIMIT 1
        """
        try:
            result = await executor.execute_query(sql)
            if result and result["results"] and len(result["results"]) > 0:
                sync_info = result["results"][0]
                
                logger.debug(f"Found sync info: {sync_info}")
                
                # Convert UTC timestamp to local time
                utc_dt = datetime.fromisoformat(str(sync_info['last_sync']))
                if utc_dt.tzinfo is None:
                    utc_dt = utc_dt.replace(tzinfo=pytz.UTC)
                
                # Get local timezone
                local_tz = datetime.now().astimezone().tzinfo
                local_time = utc_dt.astimezone(local_tz)
                
                formatted_time = local_time.strftime("%Y-%m-%d %I:%M:%S %p %Z")
                logger.info(f"Last sync time retrieved: {formatted_time}")
                return formatted_time
            
            logger.warning("No sync history found")
            return "No sync history available"
            
        except Exception as e:
            logger.error(f"Error fetching users sync history: {str(e)}", exc_info=True)
            return f"Error fetching sync time: {str(e)}"

    @staticmethod
    async def process_query(query: str) -> AsyncGenerator[str, None]:
        try:
            # Add detailed logging for query processing steps
            logger.info(f"Starting query processing: {query}")
            
            # Basic input validation
            if not query or query.strip() == "":
                logger.warning("Empty query received")
                yield json.dumps({
                    "type": "text",
                    "content": "I need a question to help you. Please provide a specific query about your Okta data."
                })
                return

            # Initialize components
            executor = SQLExecutor()
            last_sync = await AIService.get_last_sync_info(executor)
            
            # Get expanded query with detailed logging
            logger.info("Calling expand_query...")
            reasoning_result = await expand_query(query)
            logger.info(f"Reasoning expanded query: {reasoning_result['expanded_query']}")
            logger.info(f"Reasoning explanation: {reasoning_result['explanation']}")
            
            # Validate reasoning result
            if not reasoning_result or not reasoning_result.get("expanded_query"):
                logger.warning(f"Invalid reasoning result: {reasoning_result}")
                yield json.dumps({
                    "type": "text",
                    "content": "I couldn't understand your question. Please rephrase it to be more specific about Okta data."
                })
                return
                
            # Generate SQL with detailed logging
            logger.info("Generating SQL...")
            sql_response = await sql_agent.run(reasoning_result["expanded_query"])
            sql_result = extract_json_from_text(str(sql_response.data))
            logger.info(f"SQL generation result: {sql_result}")
            
            if not sql_result or not sql_result.get("sql"):
                logger.warning("No SQL generated")
                yield json.dumps({
                    "type": "text",
                    "content": "I couldn't generate a valid query. Please try rephrasing your question."
                })
                return
            
            # Execute query
            logger.info(f"Executing SQL: {sql_result['sql']}")
            query_results = await executor.execute_query(sql_result["sql"])
            
            if query_results.get("error"):
                logger.error(f"SQL execution error: {query_results['error']}")
                yield json.dumps({
                    "type": "error",
                    "content": f"Database error: {query_results['error']}"
                })
                return
                
            # Format and return results
            response = {
                "type": "stream",
                "content": query_results.get("results", []),
                "metadata": {
                    "query": reasoning_result["expanded_query"],
                    "sql": sql_result["sql"],
                    "explanation": sql_result.get("explanation", ""),
                    "last_sync": last_sync,
                    "headers": (
                        [{"text": key.title(), "value": key} 
                        for key in query_results["results"][0].keys()]
                        if query_results.get("results") and query_results["results"]
                        else []
                    )
                }
            }
            
            logger.info("Sending response to client")
            yield json.dumps(response)

        except Exception as e:
            logger.error(f"Error in process_query: {str(e)}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "content": f"An error occurred: {str(e)}"
            })
            
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            yield json.dumps({
                "status": "error", 
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })