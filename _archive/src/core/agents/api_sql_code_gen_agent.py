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

class PolarsOptimizedOutput(BaseModel):
    """Output optimized for Polars DataFrame processing - no temp tables needed"""
    id_extraction_path: str = Field(..., description="JSONPath or field name to extract IDs from API data (e.g. 'id', 'profile.login', 'actor.id')")
    sql_query_template: str = Field(..., description="SQL query with {user_ids} placeholder for IN clause")
    api_dataframe_fields: List[str] = Field(..., description="Fields to keep from API data for final JOIN")
    join_field: str = Field(..., description="Field name to join API DataFrame and SQL results on")
    explanation: str = Field(..., description="Context about what this accomplishes")
    estimated_records: int = Field(0, description="Estimated number of records")
    use_polars_optimization: bool = Field(True, description="Flag indicating this uses Polars optimization")

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
        
        # Add Polars optimization instructions to the main prompt
        self.system_prompt += self._get_polars_optimization_prompt()
        
        # Single agent for Polars optimization only
        self.agent = Agent(
            model=model,
            output_type=PolarsOptimizedOutput,
            deps_type=ApiSqlDependencies,
            system_prompt=self.system_prompt,
            retries=0
        )
        
        # Add dynamic schema access tool
        @self.agent.system_prompt
        async def okta_database_schema(ctx) -> str:
            """Access the complete okta database schema to answer user questions"""
            from src.data.schemas.shared_schema import get_okta_database_schema
            return get_okta_database_schema()
        
        logger.info(f"API-SQL Agent initialized with tenant_id: {actual_tenant_id}")

    def _get_polars_optimization_prompt(self) -> str:
        """Get additional prompt text for Polars optimization mode"""
        return """

## POLARS OPTIMIZATION MODE

You are now operating in POLARS OPTIMIZATION MODE for high-performance DataFrame processing.

Instead of generating temp table specifications, generate direct SQL queries with placeholders for dynamic user ID lists.

**OUTPUT FORMAT**: PolarsOptimizedOutput with these fields:
- `id_extraction_path`: Dot-notation path to extract IDs from API data
- `sql_query_template`: SQL query with {user_ids} placeholder for IN clause
- `api_dataframe_fields`: List of API fields to keep for final JOIN (e.g., ['id', 'email', 'status'])
- `join_field`: Field name for joining API DataFrame with SQL results (usually 'okta_id' or 'id')
- `explanation`: What this query accomplishes
- `estimated_records`: Expected number of results

**ID EXTRACTION PATHS** (Dynamic - works with ANY API structure):
- Raw string data: `"identity"` or `"self"` - extracts string directly (for simple ID lists)
- Simple field: `"id"` - extracts record["id"]
- Nested field: `"profile.login"` - extracts record["profile"]["login"]  
- Deep nesting: `"actor.alternateId"` - extracts record["actor"]["alternateId"]
- Array extraction: `"user_ids.*"` - extracts all items from record["user_ids"] array
- Application data: `"settings.app.authURL"` - extracts record["settings"]["app"]["authURL"]
- Group info: `"profile.name"` - extracts record["profile"]["name"]
- Log data: `"target.id"` - extracts record["target"]["id"]

**EXAMPLE FOR API ARRAY DATA** (API returns {'user_ids': [...], ...}):
```json
{
    "id_extraction_path": "user_ids.*",
    "sql_query_template": "SELECT okta_id, first_name, last_name, email, status FROM users WHERE okta_id IN ({user_ids}) AND tenant_id = 'dev-123456' AND is_deleted = 0",
    "api_dataframe_fields": ["user_count", "total_events"],
    "join_field": "okta_id",
    "explanation": "Extract user IDs from API array and fetch database user records",
    "estimated_records": 50
}
```

**EXAMPLE FOR USERS**:
```json
{
    "id_extraction_path": "id",
    "sql_query_template": "SELECT okta_id, first_name, last_name, email, status FROM users WHERE okta_id IN ({user_ids}) AND tenant_id = 'dev-123456' AND is_deleted = 0",
    "api_dataframe_fields": ["id", "profile.email", "status"],
    "join_field": "okta_id",
    "explanation": "Extract user IDs from API data and fetch corresponding database user records",
    "estimated_records": 50
}
```

**EXAMPLE FOR GROUPS**:
```json
{
    "id_extraction_path": "id", 
    "sql_query_template": "SELECT group_id, group_name, description FROM groups WHERE group_id IN ({user_ids}) AND tenant_id = 'dev-123456'",
    "api_dataframe_fields": ["id", "profile.name", "profile.description"],
    "join_field": "group_id",
    "explanation": "Extract group IDs and fetch database group details", 
    "estimated_records": 25
}
```

**EXAMPLE FOR LOGS**:
```json
{
    "id_extraction_path": "actor.id",
    "sql_query_template": "SELECT okta_id, first_name, last_name FROM users WHERE okta_id IN ({user_ids}) AND tenant_id = 'dev-123456'",
    "api_dataframe_fields": ["actor.id", "actor.displayName", "eventType"],
    "join_field": "okta_id", 
    "explanation": "Extract actor IDs from log events and get user details",
    "estimated_records": 100
}
```

**KEY ADVANTAGES**:
- No temp table creation/insertion overhead  
- Direct SQL execution with IN clauses
- Polars DataFrame JOIN for final result combination
- 13,964x performance improvement over temp tables

**CRITICAL RULES**:
- Always use {user_ids} placeholder for dynamic ID lists
- Include proper tenant_id filtering in SQL
- Specify exact API fields needed for final result
- Use clear join field names for DataFrame operations
"""

    async def process_api_data(self, api_data: Union[List[Dict[str, Any]], Dict[str, Any]], 
                              processing_context: str, 
                              correlation_id: str,
                              all_step_contexts: Optional[Dict[str, Any]] = None,
                              sql_tables: Optional[Dict[str, Any]] = None,
                              **kwargs) -> Any:
        """
        Process API data using Polars optimization (ONLY mode supported)
        """
        
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
            temp_table_mode=False,  # Polars optimization mode - no temp tables
            flow_id=correlation_id,
            tenant_id=tenant_id,
            sql_tables=sql_tables or {}  # Pass dynamic schema information
        )
        
        # Build user message for Polars optimization
        user_message = f"""
## USER QUERY
{processing_context}

## API DATA TO PROCESS
Records found: {len(normalized_api_data)}
Tenant ID: {tenant_id}

SAMPLE API DATA STRUCTURE:
{json.dumps(sample_data, indent=2)}

## TASK - POLARS OPTIMIZATION MODE
Generate PolarsOptimizedOutput with:
1. id_extraction_path: How to extract IDs from the API data
2. sql_query_template: SQL with {{user_ids}} placeholder for IN clause  
3. api_dataframe_fields: API fields to keep for final JOIN
4. join_field: Field name for DataFrame JOIN operations

The system will:
- Extract IDs from API data using your specified path
- Execute SQL query with IN clause (no temp tables)
- Perform final Polars DataFrame JOIN for optimal performance

Use tenant_id = '{tenant_id}' in SQL WHERE clauses.
"""
        
        if all_step_contexts:
            user_message += "\n\nPREVIOUS STEP CONTEXTS:\n"
            for step_key, step_data in all_step_contexts.items():
                if isinstance(step_data, dict):
                    context = step_data.get('context', 'No context available')
                    user_message += f"\n{step_key}_context: {context}"
                else:
                    user_message += f"\n{step_key}: {step_data}"
        
        # Execute Polars optimization agent (ONLY mode)
        try:
            logger.info(f"[{correlation_id}] Using Polars optimization mode")
            result = await self.agent.run(user_message, deps=deps)
            logger.info(f"[{correlation_id}] Polars optimization output generated")
            return result
        except Exception as e:
            logger.error(f"[{correlation_id}] Polars Agent execution failed: {str(e)}")
            raise RuntimeError(f"Polars optimization failed: {str(e)}")

# Create global instance
api_sql_code_gen_agent = ApiSqlCodeGenAgent()
