"""
Cypher Code Generation Agent for Kuzu GraphDB

This agent generates Cypher queries for the Kuzu graph database based on natural language questions.
It uses Pydantic AI for structured output and includes security validation to ensure read-only queries.

Key Features:
- Generates Kuzu-compatible Cypher queries
- Enforces UNION patterns for app access queries (direct + group-based)
- Dynamic schema injection from GraphDB
- Security validation (read-only queries only)
- Structured output with explanation and metadata

Usage:
    from src.core.agents.cypher_code_gen_agent import generate_cypher_query_with_logging
    
    result = await generate_cypher_query_with_logging(
        question="Find all active users in the Engineering department",
        tenant_id="my-tenant"
    )
    print(result.cypher_query)
"""

import logging
from typing import Optional
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.core.okta.graph_db.schema_v2_enhanced import get_graph_schema_description

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# Output Model
# ============================================================================

class CypherQueryOutput(BaseModel):
    """Structured output for Cypher query generation"""
    
    cypher_query: str = Field(
        description="The generated Cypher query (Kuzu syntax)"
    )
    explanation: str = Field(
        description="Brief explanation of what the query does and why this approach was chosen"
    )
    expected_columns: list[str] = Field(
        description="List of column names that will be returned by the query"
    )
    requires_union: bool = Field(
        default=False,
        description="True if query uses UNION for app access (direct + group-based)"
    )
    complexity: str = Field(
        description="Query complexity: simple, moderate, or complex"
    )


# ============================================================================
# Security Validation
# ============================================================================

def is_safe_cypher(query: str) -> bool:
    """
    Validate that Cypher query is read-only (no mutations).
    
    Args:
        query: The Cypher query to validate
        
    Returns:
        True if query is safe (read-only), False otherwise
    """
    query_upper = query.upper()
    
    # Dangerous operations (write operations)
    dangerous_keywords = [
        'CREATE',
        'DELETE',
        'DETACH DELETE',
        'SET',
        'REMOVE',
        'MERGE',
        'DROP',
        'ALTER',
    ]
    
    for keyword in dangerous_keywords:
        if keyword in query_upper:
            logger.warning(f"Unsafe Cypher query detected: contains '{keyword}'")
            return False
    
    return True


# ============================================================================
# Agent Setup
# ============================================================================

# Load system prompt
PROMPT_FILE = Path(__file__).parent / "prompts" / "cypher_code_gen_agent_system_prompt.txt"

try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT_TEMPLATE = f.read()
except FileNotFoundError:
    logger.error(f"System prompt file not found: {PROMPT_FILE}")
    SYSTEM_PROMPT_TEMPLATE = """You are a Cypher query generation expert for Kuzu GraphDB.
Generate safe, efficient, read-only Cypher queries based on user questions.
Schema will be injected dynamically."""

# Create agent
cypher_agent = Agent(
    model='openai:gpt-4o',
    result_type=CypherQueryOutput,
    system_prompt=SYSTEM_PROMPT_TEMPLATE,
)


@cypher_agent.system_prompt
async def inject_schema(ctx) -> str:
    """Dynamically inject graph schema into system prompt"""
    schema_description = get_graph_schema_description()
    return f"\n\n## CURRENT GRAPH SCHEMA\n\n{schema_description}"


# ============================================================================
# Main Functions
# ============================================================================

async def generate_cypher_query(
    question: str,
    tenant_id: str,
    model_override: Optional[str] = None
) -> CypherQueryOutput:
    """
    Generate a Cypher query from a natural language question.
    
    Args:
        question: Natural language question about the data
        tenant_id: Tenant ID for multi-tenancy filtering
        model_override: Optional model override (e.g., 'openai:gpt-4o-mini')
        
    Returns:
        CypherQueryOutput with generated query and metadata
        
    Raises:
        ValueError: If generated query is unsafe (contains mutations)
    """
    # Run agent
    if model_override:
        result = await cypher_agent.run(
            question,
            model=model_override,
            message_history=[],
        )
    else:
        result = await cypher_agent.run(
            question,
            message_history=[],
        )
    
    output = result.data
    
    # Security validation
    if not is_safe_cypher(output.cypher_query):
        raise ValueError(
            "Generated query contains unsafe operations (write/delete). "
            "Only read-only queries are allowed."
        )
    
    # Inject tenant_id parameter if not present
    if "$tenant_id" not in output.cypher_query and "tenant_id" in output.cypher_query:
        logger.warning("Query uses tenant_id but not as parameter - this is unsafe")
    
    return output


async def generate_cypher_query_with_logging(
    question: str,
    tenant_id: str,
    model_override: Optional[str] = None
) -> CypherQueryOutput:
    """
    Generate Cypher query with detailed logging.
    
    Wrapper around generate_cypher_query that adds logging for debugging.
    
    Args:
        question: Natural language question about the data
        tenant_id: Tenant ID for multi-tenancy filtering
        model_override: Optional model override
        
    Returns:
        CypherQueryOutput with generated query and metadata
    """
    logger.info(f"Generating Cypher query for: {question}")
    logger.info(f"Tenant ID: {tenant_id}")
    
    try:
        result = await generate_cypher_query(question, tenant_id, model_override)
        
        logger.info(f"✅ Query generated successfully")
        logger.info(f"Complexity: {result.complexity}")
        logger.info(f"Uses UNION: {result.requires_union}")
        logger.info(f"Expected columns: {', '.join(result.expected_columns)}")
        logger.debug(f"Cypher query:\n{result.cypher_query}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Query generation failed: {e}")
        raise


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_query():
        """Test the Cypher generation agent"""
        
        questions = [
            "Find all active users in the Engineering department",
            "Show me users without MFA enrolled",
            "List all applications assigned to user john@example.com",
            "Find users with custom attribute testAttrib populated",
        ]
        
        for question in questions:
            print(f"\n{'='*80}")
            print(f"Question: {question}")
            print(f"{'='*80}")
            
            try:
                result = await generate_cypher_query_with_logging(
                    question=question,
                    tenant_id="test-tenant"
                )
                
                print(f"\n📊 Generated Query:")
                print(result.cypher_query)
                print(f"\n💡 Explanation:")
                print(result.explanation)
                print(f"\n📋 Columns: {', '.join(result.expected_columns)}")
                print(f"⚡ Complexity: {result.complexity}")
                print(f"🔀 Uses UNION: {result.requires_union}")
                
            except Exception as e:
                print(f"\n❌ Error: {e}")
    
    # Run test
    asyncio.run(test_query())
