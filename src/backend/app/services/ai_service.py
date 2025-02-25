from typing import Dict, Any, AsyncGenerator
import json
from datetime import datetime
import pytz
import asyncio
from sqlalchemy import text
from src.core.helpers.okta_pre_reasoning_agent import expand_query
from src.core.helpers.okta_generate_sql import sql_agent, extract_json_from_text
from src.okta_db_sync.db.operations import DatabaseOperations
from src.utils.logging import logger

class SQLExecutor:
    def __init__(self):
        self.db = DatabaseOperations()
        logger.info("Initialized SQLExecutor")
    
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
    
    BATCH_SIZE = 10
    
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
        """
        Process a natural language query about Okta data with batch streaming.
        
        Operation sequence:
        1. Input validation
        2. Initialize executor & get sync info
        3. Expand query through reasoning
        4. Generate SQL
        5. Execute query
        6. Stream results in batches
        """
        try:
            logger.info(f"Starting query processing: {query}")
            
            # Input validation
            if not query or query.strip() == "":
                logger.warning("Empty query received")
                yield json.dumps({
                    "type": "text",
                    "content": "I need a question to help you. Please provide a specific query about your Okta data."
                })
                return
    
            # Initialize components and get sync info
            executor = SQLExecutor()
            last_sync = await AIService.get_last_sync_info(executor)
            
            # Query expansion through reasoning
            logger.info("Calling expand_query...")
            reasoning_result = await expand_query(query)
            expanded_query = reasoning_result.get('expanded_query', '')
            logger.info(f"Reasoning expanded query: {expanded_query}")
            
            if not expanded_query:
                yield json.dumps({
                    "type": "text",
                    "content": "Please ask a question related to okta entities."
                })
                return
    
            # SQL generation and validation
            logger.info("Generating SQL...")
            sql_response = await sql_agent.run(expanded_query)
            sql_result = extract_json_from_text(str(sql_response.data))
            logger.info(f"SQL generation result: {sql_result}")
            
            if not sql_result or not sql_result.get("sql"):
                logger.warning("No SQL generated")
                yield json.dumps({
                    "type": "text",
                    "content": "I couldn't generate a valid query. Please try rephrasing your question."
                })
                return
    
            # Query execution
            logger.info(f"Executing SQL: {sql_result['sql']}")
            query_results = await executor.execute_query(sql_result["sql"])
            
            if query_results.get("error"):
                logger.error(f"SQL execution error: {query_results['error']}")
                yield json.dumps({
                    "type": "error",
                    "content": f"Database error: {query_results['error']}"
                })
                return

            results = query_results.get("results", [])
            total_records = len(results)
            
            # Send initial metadata
            headers = []
            if results and len(results) > 0:
                headers = [{
                    "text": key.replace('_', ' ').title(),
                    "value": key,
                    "align": 'start'
                } for key in results[0].keys()]

            yield json.dumps({
                "type": "metadata",
                "content": {
                    "total_records": total_records,
                    "total_batches": (total_records + AIService.BATCH_SIZE - 1) // AIService.BATCH_SIZE,
                    "batch_size": AIService.BATCH_SIZE,
                    "query": expanded_query,
                    "sql": sql_result["sql"],
                    "explanation": sql_result.get("explanation", ""),
                    "last_sync": last_sync,
                    "headers": headers,
                    "timestamp": datetime.now().isoformat()
                }
            })

            # Stream results in batches
            for i in range(0, total_records, AIService.BATCH_SIZE):
                batch = results[i:i + AIService.BATCH_SIZE]
                batch_number = i // AIService.BATCH_SIZE + 1
                
                yield json.dumps({
                    "type": "batch",
                    "content": batch,
                    "metadata": {
                        "batch_number": batch_number,
                        "batch_size": len(batch),
                        "start_index": i,
                        "end_index": min(i + AIService.BATCH_SIZE, total_records)
                    }
                })
                
                # Small delay to prevent overwhelming the client
                await asyncio.sleep(0.1)

            # Send completion message
            yield json.dumps({
                "type": "complete",
                "content": {
                    "total_records": total_records,
                    "timestamp": datetime.now().isoformat()
                }
            })

        except Exception as e:
            logger.error(f"Error in process_query: {str(e)}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "content": f"An error occurred: {str(e)}"
            })