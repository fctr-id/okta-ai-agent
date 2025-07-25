"""
Internal API-SQL Agent for processing API data against SQL database
This agent is NOT exposed to end users - only used by system components
"""
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from pydantic_ai import Agent

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Use the model picker approach from the working version
try:
    from core.models.model_picker import ModelConfig, ModelType
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

class ApiSqlOutput(BaseModel):
    """Output from internal API-SQL agent"""
    temp_table_schema: Optional[str] = None
    processing_query: str
    explanation: str
    estimated_records: int
    uses_temp_table: bool = False

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
    
    async def process_api_data(self, api_data: List[Dict[str, Any]], 
                              processing_context: str, 
                              correlation_id: str,
                              use_temp_table: bool = False,
                              all_step_contexts: Optional[Dict[str, Any]] = None) -> Any:
        """Process API data with internal capabilities and enhanced context awareness"""
        
        logger.info(f"[{correlation_id}] API-SQL Agent processing {len(api_data)} records")
        logger.debug(f"[{correlation_id}] Processing context: {processing_context}")
        logger.debug(f"[{correlation_id}] Temp table mode: {use_temp_table}")
        
        # Enhanced context logging
        if all_step_contexts:
            logger.debug(f"[{correlation_id}] Enhanced context provided with {len(all_step_contexts)} previous steps")
        
        # Sample for LLM context
        sample_data = api_data[:5] if api_data else []
        
        # Create dependencies
        deps = ApiSqlDependencies(
            api_data_sample=sample_data,
            api_data_count=len(api_data),
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
        
        # Validate temp table schema if present
        if result.output.temp_table_schema:
            is_valid, error_msg = validate_internal_sql(result.output.temp_table_schema, correlation_id)
            if not is_valid:
                logger.error(f"[{correlation_id}] API-SQL Agent generated invalid temp table schema: {error_msg}")
                logger.debug(f"[{correlation_id}] Rejected schema: {result.output.temp_table_schema}")
                raise ValueError(f"Generated temp table schema failed security validation: {error_msg}")
        
        logger.info(f"[{correlation_id}] API-SQL generation completed")
        logger.debug(f"[{correlation_id}] Generated query type: {'TEMP_TABLE' if result.output.uses_temp_table else 'DIRECT'}")
        logger.debug(f"[{correlation_id}] Estimated records: {result.output.estimated_records}")
        
        # Log the complete generated query for debugging
        if result.output.uses_temp_table and result.output.temp_table_schema:
            logger.debug(f"[{correlation_id}] TEMP TABLE SCHEMA:\n{result.output.temp_table_schema}")
        logger.debug(f"[{correlation_id}] PROCESSING QUERY:\n{result.output.processing_query}")
        logger.debug(f"[{correlation_id}] EXPLANATION: {result.output.explanation}")
        
        return result

# Create global instance
api_sql_code_gen_agent = ApiSqlCodeGenAgent()
