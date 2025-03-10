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
from datetime import timezone, datetime, timedelta
from src.config.settings import settings 

class SQLExecutor:
    def __init__(self):
        self.db = DatabaseOperations()
        logger.info("Initialized SQLExecutor")
    
    @staticmethod
    async def validate_sql(sql: str) -> bool:
        """Validate SQL query for safety"""
        try:
            logger.debug(f"Validating SQL query: {sql}")
            
            if not sql.upper().strip().startswith('SELECT'):
                logger.warning(f"Non-SELECT query attempted: {sql}")
                raise Exception("Invalid query type")
                
            dangerous_ops = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'TRUNCATE', 'ALTER']
            for op in dangerous_ops:
                if f" {op} " in sql.upper():
                    logger.warning(f"Dangerous operation {op} found in query: {sql}")
                    raise Exception("Invalid query type")
            
            return True
        except Exception as e:
            logger.error(f"SQL validation failed: {str(e)}")
            raise Exception("Invalid query type")
    
    async def execute_query(self, sql: str) -> Dict[str, Any]:
        """Execute SQL query and return formatted results"""
        try:
            logger.debug(f"Starting query execution: {sql}")
            
            if not await self.validate_sql(sql):
                raise Exception("Invalid query type")
                
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
            return {"error": "Error processing request. Please try again."}

class AIService:
    
    BATCH_SIZE = 100
    
    @staticmethod
    async def get_last_sync_info(executor: SQLExecutor) -> Dict[str, Any]:
        """Get sync timestamp for the most recent successful sync"""
        from src.utils.logging import logger
        
        try:
            # Simple query that just gets the timestamp
            query = """
            SELECT 
                end_time
            FROM sync_history
            WHERE tenant_id = :tenant_id
            AND success = 1
            ORDER BY start_time DESC
            LIMIT 1
            """
            
            # Execute query with parameters
            params = {"tenant_id": settings.tenant_id}
            
            # Use session to execute query
            async with executor.db.get_session() as session:
                sql_text = text(query)
                result = await session.execute(sql_text, params)
                row = result.fetchone()
                
                # Default response if no data
                if not row or not row[0]:
                    return {"last_sync": "No data"}
                
                # Get timestamp as string from result
                timestamp_str = row[0]
                
                # Return the timestamp as-is - frontend will handle formatting
                return {"last_sync": timestamp_str}
            
        except Exception as e:
            # Keep error logging (always important)
            logger.error(f"Error retrieving sync timestamp: {str(e)}")
            return {"last_sync": "Error"}

    @staticmethod
    async def process_query(query: str) -> AsyncGenerator[str, None]:
        """Process a natural language query about Okta data with batch streaming."""
        try:
            logger.info(f"Starting query processing: {query}")
            
            if not query or query.strip() == "":
                yield json.dumps({
                    "type": "error",
                    "content": "Please provide a specific question about your Okta data."
                })
                return
    
            executor = SQLExecutor()
            last_sync = await AIService.get_last_sync_info(executor)
            
            logger.info("Expanding query...")
            reasoning_result = await expand_query(query)
            expanded_query = reasoning_result.get('expanded_query', '')
            logger.info(f"Expanded query: {expanded_query}")
            
            if not expanded_query:
                yield json.dumps({
                    "type": "error",
                    "content": "Please ask a question relevant to Okta users, groups, or applications."
                })
                return
    
            logger.info("Generating SQL...")
            sql_response = await sql_agent.run(expanded_query)
            sql_result = extract_json_from_text(str(sql_response.data))
            
            if not sql_result or not sql_result.get("sql"):
                yield json.dumps({
                    "type": "error",
                    "content": "I couldn't process your request. Please try rephrasing your question."
                })
                return
    
            logger.info(f"Executing SQL: {sql_result['sql']}")
            query_results = await executor.execute_query(sql_result["sql"])
            
            if query_results.get("error"):
                yield json.dumps({
                    "type": "error",
                    "content": "Error processing request. Please try again."
                })
                return

            results = query_results.get("results", [])
            total_records = len(results)
            
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
                
                await asyncio.sleep(0.1)

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
                "content": "Error processing request. Please try again."
            })