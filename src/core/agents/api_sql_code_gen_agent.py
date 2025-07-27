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

logger = get_logger(__name__)

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

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import os
import logging

logger = logging.getLogger(__name__)

class TableColumn(BaseModel):
    """Definition of a temp table column"""
    name: str = Field(..., description="Column name (alphanumeric + underscore only)")
    type: str = Field(..., description="Column type (TEXT, INTEGER, REAL, BLOB only)")
    primary_key: bool = Field(False, description="Whether this column is the primary key")
    required: bool = Field(True, description="Whether this column is required")

class TableStructure(BaseModel):
    """Definition of temp table structure"""
    columns: List[TableColumn] = Field(..., description="List of table columns")

class DataMapping(BaseModel):
    """Definition of how to map API data to table columns"""
    source_field: str = Field(..., description="Field name in API data (or special tokens like '@item')")
    target_column: str = Field(..., description="Target column name in temp table")
    required: bool = Field(True, description="Whether this mapping is required")
    default_value: Optional[str] = Field(None, description="Default value if source field is missing")

class DataExtraction(BaseModel):
    """Definition of how to extract data from API response"""
    extraction_type: str = Field(..., description="Type of extraction: 'dictionary_mapping', 'list_values', 'nested_extraction'")
    mappings: List[DataMapping] = Field(..., description="List of data mappings")

class ApiSqlOutput(BaseModel):
    """Output from internal API-SQL agent"""
    table_structure: Optional[TableStructure] = Field(None, description="Structure for temporary table if needed")
    data_extraction: Optional[DataExtraction] = Field(None, description="Instructions for extracting API data")
    processing_query: str = Field(..., description="SQL query to process the data")
    explanation: str = Field(..., description="Context about what this query accomplishes")
    estimated_records: int = Field(0, description="Estimated number of records")
    uses_temp_table: bool = Field(False, description="Whether this query uses a temporary table")

def load_api_sql_code_gen_agent_system_prompt() -> str:
    """Load system prompt from external file"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), 'prompts', 'api_sql_code_gen_agent_system_prompt.txt')
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"System prompt file not found: {prompt_file}")
        raise FileNotFoundError(f"Could not load API SQL code generation agent system prompt from {prompt_file}")

class ApiSqlCodeGenAgent:
    """Internal SQL code generation agent for API data processing - NOT exposed to users"""
    
    def __init__(self):
        self.system_prompt = load_api_sql_code_gen_agent_system_prompt()
        self.agent = Agent(
            model=model,
            output_type=ApiSqlOutput,
            deps_type=ApiSqlDependencies,
            system_prompt=self.system_prompt,
            retries=0
        )
        
        # Add system prompt function for schema access
        @self.agent.system_prompt
        async def database_schema_access(ctx) -> str:
            """Provide database schema to the internal API-SQL agent"""
            return self.get_database_schema()
        
        logger.info("Internal API-SQL Agent initialized")

    @staticmethod
    def get_database_schema() -> str:
        """Get the database schema for the API SQL agent"""
        from src.data.schemas.shared_schema import get_okta_database_schema
        return get_okta_database_schema()
    
    async def process_api_data(self, api_data: Union[List[Dict[str, Any]], Dict[str, Any]], 
                              processing_context: str, 
                              correlation_id: str,
                              use_temp_table: bool = False,
                              all_step_contexts: Optional[Dict[str, Any]] = None) -> Any:
        """Process API data with internal capabilities and enhanced context awareness"""
        
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
        logger.debug(f"[{correlation_id}] Temp table mode: {use_temp_table}")
        
        # Enhanced context logging
        if all_step_contexts:
            logger.debug(f"[{correlation_id}] Enhanced context provided with {len(all_step_contexts)} previous steps")
        
        # Sample for LLM context
        sample_data = normalized_api_data[:5] if normalized_api_data else []
        
        # Create dependencies
        deps = ApiSqlDependencies(
            api_data_sample=sample_data,
            api_data_count=len(normalized_api_data),
            processing_context=processing_context,
            temp_table_mode=use_temp_table,
            flow_id=correlation_id
        )
        
        # Build enhanced user message with previous step contexts
        user_message = processing_context
        if all_step_contexts:
            user_message += "\n\nPREVIOUS STEP CONTEXTS:\n"
            for step_key, step_data in all_step_contexts.items():
                if isinstance(step_data, dict):
                    context = step_data.get('context', 'No context available')
                    sample = step_data.get('sample', 'No sample available')
                    user_message += f"\n{step_key}_context: {context}"
                    user_message += f"\n{step_key}_sample: {sample}"
                else:
                    user_message += f"\n{step_key}: {step_data}"
        
        # Execute internal agent with enhanced context
        result = await self.agent.run(user_message, deps=deps)
        
        # Validate generated SQL for security
        from core.security.sql_security_validator import validate_internal_sql
        
        # Validate the main processing query
        if result.output.processing_query:
            is_valid, error_msg = validate_internal_sql(result.output.processing_query, correlation_id)
            if not is_valid:
                logger.error(f"[{correlation_id}] API-SQL Agent generated invalid SQL: {error_msg}")
                logger.debug(f"[{correlation_id}] Rejected SQL: {result.output.processing_query}")
                raise ValueError(f"Generated SQL failed security validation: {error_msg}")
        
        # Validate table structure if present (new secure approach)
        if result.output.uses_temp_table and result.output.table_structure:
            logger.debug(f"[{correlation_id}] Validating table structure specification")
            try:
                # Basic validation of table structure
                columns = result.output.table_structure.columns
                if not columns:
                    raise ValueError("Table structure must have at least one column")
                
                # Validate column types
                allowed_types = {'TEXT', 'INTEGER', 'REAL', 'BLOB'}
                for col in columns:
                    if col.type.upper() not in allowed_types:
                        raise ValueError(f"Invalid column type: {col.type}")
                        
                logger.debug(f"[{correlation_id}] Table structure validation passed: {len(columns)} columns")
            except Exception as e:
                logger.error(f"[{correlation_id}] Table structure validation failed: {e}")
                raise ValueError(f"Invalid table structure: {e}")
        
        logger.info(f"[{correlation_id}] API-SQL generation completed")
        logger.debug(f"[{correlation_id}] Generated query type: {'TEMP_TABLE' if result.output.uses_temp_table else 'DIRECT'}")
        logger.debug(f"[{correlation_id}] Estimated records: {result.output.estimated_records}")
        
        # Log the complete generated query for debugging
        if result.output.uses_temp_table and result.output.table_structure:
            logger.debug(f"[{correlation_id}] TABLE STRUCTURE: {len(result.output.table_structure.columns)} columns")
            logger.debug(f"[{correlation_id}] DATA EXTRACTION: {result.output.data_extraction.extraction_type}")
        logger.debug(f"[{correlation_id}] PROCESSING QUERY:\n{result.output.processing_query}")
        logger.debug(f"[{correlation_id}] EXPLANATION: {result.output.explanation}")
        
        return result

# Create global instance
api_sql_code_gen_agent = ApiSqlCodeGenAgent()
