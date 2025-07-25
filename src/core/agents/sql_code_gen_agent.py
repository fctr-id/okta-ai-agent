from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from dotenv import load_dotenv
import asyncio
import os
import json
import re
import sys
from typing import List, Dict, Any, Optional

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logging import get_logger, generate_correlation_id, set_correlation_id, get_default_log_dir

load_dotenv()

# Setup centralized logging with file output
logger = get_logger("okta_ai_agent.sql_agent", log_dir=get_default_log_dir())

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

@dataclass
class SQLDependencies:
    tenant_id: str
    include_deleted: bool = False
    flow_id: str = ""  # Correlation ID for flow tracking

class SQLQueryOutput(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT * FROM users ",
            "explanation": "This query fetches all active users from the database"
        }
    })

    sql: str = Field(
        description='SQL query to execute to fetch the details requested in the user question',
        min_length=1
    )
    explanation: str = Field(
        description='Natural language explanation for the SQL query provided',
        min_length=1
    )

    def json_response(self) -> str:
        """Returns a properly formatted JSON string"""
        return self.model_dump_json(indent=2)

# Replace the existing system_prompt content with this updated version:

# Load the system prompt from external file
def load_sql_code_gen_agent_system_prompt():
    """Load SQL code generation agent system prompt from external text file"""
    prompt_file = os.path.join(os.path.dirname(__file__), 'prompts', 'sql_code_gen_agent_system_prompt.txt')
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        # Minimal fallback if external file not found
        logger.warning("SQL code generation agent system prompt file not found, using minimal fallback")
        return "You are an expert SQLite engineer. Always include okta_id for all entities. Generate a single valid SQLite query with proper JSON output format."

sql_agent = Agent(
    model,
    output_type=SQLQueryOutput,
    deps_type=SQLDependencies,
    retries=0,  # Keep simple - no retries to avoid validation issues
    system_prompt=load_sql_code_gen_agent_system_prompt()
)

@sql_agent.system_prompt
async def okta_database_schema(ctx: RunContext[SQLDependencies]) -> str:
    """Access the complete okta database schema to answer user questions"""
    from src.data.schemas.shared_schema import get_okta_database_schema
    return get_okta_database_schema()

def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text response"""
    try:
        # First try direct JSON parsing
        return json.loads(text)
    except json.JSONDecodeError:
        # Look for JSON in code blocks
        try:
            code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            matches = re.findall(code_block_pattern, text)
            if matches:
                for match in matches:
                    try:
                        return json.loads(match)
                    except json.JSONDecodeError:
                        continue
        except re.error:
            pass

        # Try to find the first valid JSON object using bracket counting
        try:
            start_idx = text.find('{')
            if start_idx >= 0:
                level = 0
                for i in range(start_idx, len(text)):
                    if text[i] == '{':
                        level += 1
                    elif text[i] == '}':
                        level -= 1
                        if level == 0:
                            json_str = text[start_idx:i+1]
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError:
                                pass
        except Exception:
            pass

        # If we get here, we couldn't find valid JSON
        raise ValueError(f"No valid JSON found in response: {text[:100]}...")

def is_safe_sql(sql_query: str, flow_id: str = "") -> bool:
    """Enhanced SQL safety check using comprehensive security validator"""
    from core.security.sql_security_validator import validate_user_sql
    
    is_valid, error_msg = validate_user_sql(sql_query, flow_id)
    
    if not is_valid:
        logger.warning(f"[{flow_id}] SQL validation failed: {error_msg}")
        logger.debug(f"[{flow_id}] Rejected SQL: {sql_query}")
    
    return is_valid

async def main():
    print("\nWelcome to Okta Query Assistant!")
    print("Type 'exit' to quit\n")

    while True:
        question = input("\nWhat would you like to know about your Okta data? > ")
        if question.lower() == 'exit':
            break

        # Generate correlation ID for this query
        flow_id = generate_correlation_id()
        set_correlation_id(flow_id)

        try:
            logger.info(f"[{flow_id}] SQL Agent: Starting query generation")
            logger.debug(f"[{flow_id}] Input query: {question}")
            
            # Use structured output directly (no manual JSON parsing needed)
            deps = SQLDependencies(tenant_id="default", include_deleted=False, flow_id=flow_id)
            result = await sql_agent.run(question, deps=deps)
            
            logger.debug(f"[{flow_id}] Generated SQL: {result.output.sql}")
            logger.debug(f"[{flow_id}] SQL Explanation: {result.output.explanation}")
            
            # Simple token usage reporting (keeping it minimal)
            if hasattr(result, 'usage') and result.usage():
                usage = result.usage()
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                logger.info(f"[{flow_id}] SQL generation completed - {input_tokens} in, {output_tokens} out tokens")
                print(f"Token Usage: {input_tokens} in, {output_tokens} out")

            print("\nGenerated SQL:")
            print("-" * 40)
            print(result.output.sql)
            print("\nExplanation:")
            print(result.output.explanation)

        except ModelRetry as e:
            logger.error(f"[{flow_id}] SQL generation retry needed: {e}")
            print(f"\nRetry needed: {e}")
        except UnexpectedModelBehavior as e:
            logger.error(f"[{flow_id}] SQL generation unexpected behavior: {e}")
            print(f"\nUnexpected behavior: {e}")
        except UsageLimitExceeded as e:
            logger.error(f"[{flow_id}] SQL generation usage limit exceeded: {e}")
            print(f"\nUsage limit exceeded: {e}")
        except Exception as e:
            logger.error(f"[{flow_id}] SQL generation failed: {e}")
            print(f"\nError: {str(e)}")

        print("-" * 80)


async def generate_sql_query_with_logging(question: str, tenant_id: str = "default", include_deleted: bool = False, flow_id: str = None, all_step_contexts: Optional[Dict[str, Any]] = None) -> dict:
    """
    Wrapper function for SQL agent with enhanced debug logging and context awareness.
    
    This function provides the debug logging that shows the complete SQL queries
    and explanations that were missing when calling sql_agent.run() directly.
    
    Args:
        question: The SQL question to generate query for
        tenant_id: Tenant identifier
        include_deleted: Whether to include deleted records
        flow_id: Flow correlation ID
        all_step_contexts: Enhanced context from all previous steps
    """
    if not flow_id:
        flow_id = generate_correlation_id()
    
    try:
        logger.info(f"[{flow_id}] SQL Agent: Starting query generation")
        logger.debug(f"[{flow_id}] Input query: {question}")
        
        # Enhanced context logging
        if all_step_contexts:
            logger.debug(f"[{flow_id}] Enhanced context provided with {len(all_step_contexts)} previous steps")
        
        # Build enhanced user message with previous step contexts
        user_message = question
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
        
        # Use structured output directly (no manual JSON parsing needed)
        deps = SQLDependencies(tenant_id=tenant_id, include_deleted=include_deleted, flow_id=flow_id)
        result = await sql_agent.run(user_message, deps=deps)
        
        logger.debug(f"[{flow_id}] Generated SQL: {result.output.sql}")
        logger.debug(f"[{flow_id}] SQL Explanation: {result.output.explanation}")
        
        # Validate SQL for security before returning
        if not is_safe_sql(result.output.sql, flow_id):
            logger.error(f"[{flow_id}] Generated SQL failed security validation")
            return {
                'success': False,
                'error': 'Generated SQL query failed security validation',
                'sql': '',
                'explanation': 'The generated query contains potentially unsafe operations and was blocked for security reasons.'
            }
        
        # Token usage reporting
        if hasattr(result, 'usage') and result.usage():
            usage = result.usage()
            input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
            output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
            logger.info(f"[{flow_id}] SQL generation completed - {input_tokens} in, {output_tokens} out tokens")

        return {
            'success': True,
            'sql': result.output.sql,
            'explanation': result.output.explanation,
            'usage': result.usage() if hasattr(result, 'usage') and result.usage() else None
        }

    except ModelRetry as e:
        logger.error(f"[{flow_id}] SQL generation retry needed: {e}")
        return {'success': False, 'error': f"Retry needed: {e}"}
    except UnexpectedModelBehavior as e:
        logger.error(f"[{flow_id}] SQL generation unexpected behavior: {e}")
        return {'success': False, 'error': f"Unexpected behavior: {e}"}
    except UsageLimitExceeded as e:
        logger.error(f"[{flow_id}] SQL generation usage limit exceeded: {e}")
        return {'success': False, 'error': f"Usage limit exceeded: {e}"}
    except Exception as e:
        logger.error(f"[{flow_id}] SQL generation failed: {e}")
        return {'success': False, 'error': str(e)}


if __name__ == "__main__":
    asyncio.run(main())
