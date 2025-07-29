"""
Internal API-SQL Agent for processing API data against SQL database
This agent is NOT exposed to end users - only used by system components
"""
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from pydantic_ai import Agent

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.logging import get_logger

# Using main "okta_ai_agent" namespace for unified logging across all agents
logger = get_logger("okta_ai_agent")

# Use the model picker approach from the working version
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    def get_simple_model():
        """Simple model configuration without complex imports"""
        model_name = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
        return model_name
    model = get_simple_model()

class ApiSqlDependencies(BaseModel):
    """Dependencies for internal API-SQL processing - flexible data flow"""
    api_data_sample: Any  # Completely flexible - let LLM handle any data type
    api_data_count: int
    processing_context: str
    temp_table_mode: bool = False
    system_mode: bool = True
    flow_id: str
    tenant_id: str = "main"
    sql_tables: Dict[str, Any] = {}  # Dynamic schema from okta_schema.json

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import os
import logging

# Note: logger already defined above with unified "okta_ai_agent" namespace

class SqlStatementsOutput(BaseModel):
    """Output from SQL generation agent"""
    sql_statements: List[str] = Field(..., description="Complete SQL statements: CREATE, INSERT, SELECT")
    explanation: str = Field(..., description="Context about what the SQL accomplishes")
    estimated_records: int = Field(0, description="Estimated number of records")
    extraction_summary: str = Field(..., description="Summary of data extraction approach")

def load_api_sql_system_prompt() -> str:
    """Load API-SQL system prompt from external file"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), 'prompts', 'api_sql_code_gen_agent_system_prompt.txt')
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"API-SQL system prompt file not found: {prompt_file}")
        raise

class ApiSqlCodeGenAgent:
    """Internal SQL code generation agent for API data processing"""
    
    def __init__(self):
        self.system_prompt = load_api_sql_system_prompt()
        
        # Get tenant_id from settings and add it dynamically to the prompt
        from src.config.settings import settings
        actual_tenant_id = settings.tenant_id
        
        # Add tenant_id as a dynamic variable at the end of the system prompt
        self.system_prompt += f"\n\n## DYNAMIC SQL VARIABLES\n\nSQL_TENANT_ID = '{actual_tenant_id}'\n\nWhen generating SQL queries, use the SQL_TENANT_ID value above for any tenant_id conditions.\nExample: WHERE u.tenant_id = '{actual_tenant_id}' AND u.is_deleted = 0"
        
        self.agent = Agent(
            model=model,
            output_type=SqlStatementsOutput,
            deps_type=ApiSqlDependencies,
            system_prompt=self.system_prompt,
            retries=0
        )
        
        # Add dynamic schema access tool (same pattern as SQL agent)
        @self.agent.system_prompt
        async def okta_database_schema(ctx) -> str:
            """Access the complete okta database schema to answer user questions"""
            from src.data.schemas.shared_schema import get_okta_database_schema
            return get_okta_database_schema()
        
        # Import SQL security validation
        from src.utils.security_config import validate_sql_for_execution
        self.validate_sql = validate_sql_for_execution
        
        logger.info(f"API-SQL Agent initialized with tenant_id: {actual_tenant_id}")

    async def process_api_data(self, api_data: Union[List[Dict[str, Any]], Dict[str, Any]], 
                              processing_context: str, 
                              correlation_id: str,
                              use_temp_table: bool = False,
                              all_step_contexts: Optional[Dict[str, Any]] = None,
                              sql_tables: Optional[Dict[str, Any]] = None) -> Any:
        """Process API data using direct SQL generation - creates temp table and JOINs with existing database"""
        
        # Normalize api_data to always be a list for consistent processing
        if isinstance(api_data, dict):
            # Single dictionary result - convert to list
            normalized_api_data = [api_data]
        elif isinstance(api_data, list):
            # Already a list
            normalized_api_data = api_data
        else:
            # Fallback for other types
            normalized_api_data = []
            logger.warning(f"[{correlation_id}] Unexpected api_data type: {type(api_data)}, using empty list")
        
        logger.info(f"[{correlation_id}] API-SQL Agent processing {len(normalized_api_data)} records")
        logger.debug(f"[{correlation_id}] Processing context: {processing_context}")
        
        # Enhanced context logging
        if all_step_contexts:
            logger.debug(f"[{correlation_id}] Enhanced context provided with {len(all_step_contexts)} previous steps")
        
        # Get tenant ID for SQL replacement
        from src.config.settings import settings
        tenant_id = settings.tenant_id
        
        # Sample for LLM context
        sample_data = normalized_api_data[:5] if normalized_api_data else []
        
        # Create dependencies
        deps = ApiSqlDependencies(
            api_data_sample=sample_data,
            api_data_count=len(normalized_api_data),
            processing_context=processing_context,
            temp_table_mode=True,  # Always use temp tables for database JOINs
            flow_id=correlation_id,
            tenant_id=tenant_id,
            sql_tables=sql_tables or {}  # Pass dynamic schema information
        )
        
        # Build user message with actual API data
        user_message = f"""
## USER QUERY
{processing_context}

## API DATA TO CONVERT TO SQL
Records found: {len(normalized_api_data)}
Tenant ID: {tenant_id}

ACTUAL API DATA TO ANALYZE:
{json.dumps(sample_data, indent=2)}

## TASK
Generate complete SQL statements (CREATE TEMPORARY TABLE, INSERT statements, SELECT query) 
to process this API data and answer the user's query.

Remember:
- Use tenant_id = 'TENANT_PLACEHOLDER' in WHERE clauses
- Include all relationship identifiers for proper data linking
- Generate one INSERT per API record
- Ensure SQL security compliance
- JOIN with existing database tables to find related data (groups, applications, etc.)
"""
        
        if all_step_contexts:
            user_message += "\n\nPREVIOUS STEP CONTEXTS:\n"
            for step_key, step_data in all_step_contexts.items():
                if isinstance(step_data, dict):
                    context = step_data.get('context', 'No context available')
                    user_message += f"\n{step_key}_context: {context}"
                else:
                    user_message += f"\n{step_key}: {step_data}"
        
        # Execute SQL generation agent
        try:
            result = await self.agent.run(user_message, deps=deps)
        except Exception as e:
            logger.error(f"[{correlation_id}] SQL Agent execution failed: {str(e)}")
            raise RuntimeError(f"SQL generation failed: {str(e)}")
        
        # Validate that we got sql_statements
        if not hasattr(result.output, 'sql_statements') or not result.output.sql_statements:
            raise ValueError("SQL agent failed to generate sql_statements")
        
        # Replace tenant placeholder with actual tenant ID
        processed_statements = []
        for stmt in result.output.sql_statements:
            processed_stmt = stmt.replace('TENANT_PLACEHOLDER', tenant_id)
            processed_statements.append(processed_stmt)
        
        # Validate SQL security
        is_valid, error_msg = self.validate_sql(processed_statements)
        if not is_valid:
            logger.error(f"[{correlation_id}] SQL Agent generated invalid SQL: {error_msg}")
            logger.debug(f"[{correlation_id}] Rejected SQL statements: {processed_statements}")
            raise ValueError(f"Generated SQL failed security validation: {error_msg}")
        
        logger.info(f"[{correlation_id}] SQL generation completed with {len(processed_statements)} statements")
        logger.debug(f"[{correlation_id}] SQL security validation passed")
        
        # Create compatible result object for existing execution manager
        class SqlResult:
            def __init__(self, sql_statements, explanation, estimated_records, extraction_summary):
                self.sql_statements = sql_statements
                self.explanation = explanation
                self.estimated_records = estimated_records
                self.extraction_summary = extraction_summary
                
                # Create a fake output object for compatibility
                self.output = type('obj', (object,), {
                    'processing_query': sql_statements[-1] if sql_statements else '',  # Last statement is typically SELECT
                    'explanation': explanation,
                    'estimated_records': estimated_records,
                    'uses_temp_table': True,
                    'sql_statements': sql_statements
                })()
        
        return SqlResult(
            processed_statements,
            result.output.explanation,
            int(result.output.estimated_records) if str(result.output.estimated_records).isdigit() else len(normalized_api_data),
            result.output.extraction_summary
        )

# Create global instance
api_sql_code_gen_agent = ApiSqlCodeGenAgent()
