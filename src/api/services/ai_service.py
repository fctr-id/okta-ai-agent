from typing import Dict, Any, AsyncGenerator, Optional
import json
from datetime import datetime
import pytz
import asyncio
from sqlalchemy import text
from legacy.sql_mode.okta_pre_reasoning_agent import expand_query
from legacy.sql_mode.okta_generate_sql import sql_agent, extract_json_from_text
from core.okta.sync.operations import DatabaseOperations
from utils.logging import logger
from datetime import timezone, datetime, timedelta
from config.settings import settings 

class SQLExecutor:
    def __init__(self):
        self.db = DatabaseOperations()
        self._current_session = None  # Track current active session
        self._cancelled = False       # Track cancellation state
        logger.info("Initialized SQLExecutor")
    
    def cancel(self):
        """Cancel any ongoing operation"""
        logger.info("Cancelling ongoing SQL execution")
        self._cancelled = True
        # Close the session if it's active
        if self._current_session:
            asyncio.create_task(self._close_session())
    
    async def _close_session(self):
        """Close the current session safely"""
        try:
            if self._current_session:
                await self._current_session.close()
                logger.info("Database session closed due to cancellation")
        except Exception as e:
            logger.error(f"Error closing session: {str(e)}")
        finally:
            self._current_session = None
    
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
            
            # Reset cancellation flag before starting
            self._cancelled = False
            
            async with self.db.get_session() as session:
                # Store the session for potential cancellation
                self._current_session = session
                
                # Check if already cancelled
                if self._cancelled:
                    logger.info("Query execution cancelled before SQL execution")
                    return {"error": "Query cancelled", "cancelled": True}
                
                logger.debug("Database session created")
                sql_text = text(sql)
                
                # Execute with timeout to prevent extremely long-running queries
                try:
                    query_result = await asyncio.wait_for(
                        session.execute(sql_text),
                        timeout=60.0  # 60 second timeout for query execution
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Query execution timed out: {sql}")
                    return {"error": "Query timed out. Please try a more specific query."}
                
                # Clear session reference after successful execution
                self._current_session = None
                
                # Check if cancelled during execution
                if self._cancelled:
                    logger.info("Query execution cancelled after SQL execution")
                    return {"error": "Query cancelled", "cancelled": True}
                
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
            if self._cancelled:
                return {"error": "Query cancelled", "cancelled": True}
            return {"error": "Error processing request. Please try again."}
        finally:
            # Always clear the session reference
            self._current_session = None

class AIService:
    
    BATCH_SIZE = 500
    
    @staticmethod
    async def get_last_sync_info(executor: SQLExecutor) -> Dict[str, Any]:
        """Get sync timestamp for the most recent successful sync"""
        from utils.logging import logger
        
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
    async def process_query(query: str, request_alive_callback: Optional[callable] = None) -> AsyncGenerator[str, None]:
        """
        Process a natural language query about Okta data with batch streaming.
        
        Args:
            query: The natural language query to process
            request_alive_callback: Callback function that returns False if request is cancelled
        """
        executor = None
        try:
            logger.info(f"Starting query processing: {query}")
            
            if not query or query.strip() == "":
                yield json.dumps({
                    "type": "error",
                    "content": "Please provide a specific question about your Okta data."
                })
                return
    
            executor = SQLExecutor()
            
            # Helper function to check if request is still alive
            def is_cancelled():
                if request_alive_callback and not request_alive_callback():
                    return True
                return False
    
            # Get last sync info
            last_sync = await AIService.get_last_sync_info(executor)
            
            # Check if cancelled
            if is_cancelled():
                logger.info("Request cancelled before query expansion")
                yield json.dumps({
                    "type": "error",
                    "content": "Request cancelled by user.",
                    "cancelled": True
                })
                return
            
            # Expand query
            logger.info("Expanding query...")
            reasoning_result = await expand_query(query)
            expanded_query = reasoning_result.get('expanded_query', '')
            logger.info(f"Expanded query: {expanded_query}")
            
            # Check if cancelled
            if is_cancelled():
                logger.info("Request cancelled after query expansion")
                yield json.dumps({
                    "type": "error",
                    "content": "Request cancelled by user.",
                    "cancelled": True
                })
                return
            
            if not expanded_query:
                yield json.dumps({
                    "type": "error",
                    "content": "Please ask a question relevant to Okta users, groups, or applications."
                })
                return
    
            # Generate SQL
            logger.info("Generating SQL...")
            sql_response = await sql_agent.run(expanded_query)
            sql_result = extract_json_from_text(str(sql_response.output))
            
            # Check if cancelled
            if is_cancelled():
                logger.info("Request cancelled after SQL generation")
                yield json.dumps({
                    "type": "error",
                    "content": "Request cancelled by user.",
                    "cancelled": True
                })
                return
            
            if not sql_result or not sql_result.get("sql"):
                yield json.dumps({
                    "type": "error",
                    "content": "I couldn't process your request. Please try rephrasing your question."
                })
                return
    
            # Execute SQL
            logger.info(f"Executing SQL: {sql_result['sql']}")
            query_results = await executor.execute_query(sql_result["sql"])
            
            # Check if cancelled or if query execution failed due to cancellation
            if is_cancelled() or (query_results.get("cancelled")):
                logger.info("Request cancelled during or after SQL execution")
                executor.cancel()  # Ensure any ongoing operations are cancelled
                yield json.dumps({
                    "type": "error",
                    "content": "Request cancelled by user.",
                    "cancelled": True
                })
                return
            
            if query_results.get("error"):
                yield json.dumps({
                    "type": "error",
                    "content": query_results.get("error")
                })
                return

            # Process results
            results = query_results.get("results", [])

            # Smart Expansion: Backend processing for custom attributes
            # If 'custom_attributes' column exists, parse its JSON content
            # and merge it into the main result row.
            if results and 'custom_attributes' in results[0]:
                logger.info(f"Processing {len(results)} results with custom_attributes column")
                transformed_results = []
                users_with_attrs = 0
                for i, row in enumerate(results):
                    new_row = dict(row)
                    custom_attrs_json = new_row.pop('custom_attributes', None)
                    
                    if custom_attrs_json and isinstance(custom_attrs_json, str) and custom_attrs_json != '{}':
                        try:
                            custom_attrs = json.loads(custom_attrs_json)
                            if isinstance(custom_attrs, dict) and custom_attrs:
                                new_row.update(custom_attrs)
                                users_with_attrs += 1
                        except (json.JSONDecodeError, TypeError):
                            # If JSON is invalid or not a string, skip custom attributes for this row
                            pass
                    
                    transformed_results.append(new_row)
                results = transformed_results
                
                # Find a row with custom attributes to show proper column structure
                sample_keys = list(results[0].keys()) if results else []
                if users_with_attrs > 0:
                    # Find first row that has custom attributes to show complete column structure
                    for row in results:
                        # Check if this row has any custom attribute columns
                        base_columns = {'email', 'login', 'first_name', 'last_name', 'status', 'created_at', 'id', 'profile_url'}
                        row_keys = set(row.keys())
                        if row_keys - base_columns:  # Has custom attributes
                            sample_keys = list(row.keys())
                            break
                
                logger.info(f"Custom attributes transformation completed. {users_with_attrs} users had custom attributes.")
            else:
                logger.info(f"No custom_attributes column found in results. Available columns: {list(results[0].keys()) if results else 'No results'}")

            total_records = len(results)
            
            headers = []
            if results and len(results) > 0:
                # Use sample_keys if we processed custom attributes, otherwise use first row keys
                keys_to_use = sample_keys if 'sample_keys' in locals() else list(results[0].keys())
                headers = [{
                    "text": key.replace('_', ' ').title(),
                    "value": key,
                    "align": 'start'
                } for key in keys_to_use]

            # Send metadata
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
                # Check if cancelled before sending each batch
                if is_cancelled():
                    logger.info(f"Request cancelled during batch streaming (at batch {i // AIService.BATCH_SIZE + 1})")
                    yield json.dumps({
                        "type": "error",
                        "content": "Request cancelled by user.",
                        "cancelled": True
                    })
                    return
                
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
                
                # Small delay between batches
                await asyncio.sleep(0.1)

            # Complete message
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
        finally:
            # Always ensure cleanup happens
            if executor and hasattr(executor, 'cancel') and is_cancelled():
                logger.info("SQL request cancelled by user")
                executor.cancel()