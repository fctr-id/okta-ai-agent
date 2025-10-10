"""
Cypher Code Generation Agent for Kuzu GraphDB

This agent generates Cypher queries for the Kuzu graph database based on natural language questions.
It uses Pydantic AI for structured output and includes security validation to ensure read-only queries.

Key Features:
- TWO MODES: Direct (user questions) and Enrichment (API data)
- Generates Kuzu-compatible Cypher queries
- Enforces UNION patterns for app access queries (direct + group-based)
- Dynamic schema injection from GraphDB
- Security validation (read-only queries only)
- Polars optimization for API data enrichment (13,964x faster)
- Structured output with explanation and metadata

Usage (Direct Mode):
    from src.core.agents.cypher_code_gen_agent import generate_cypher_query_with_logging
    
    result = await generate_cypher_query_with_logging(
        question="Find all active users in the Engineering department",
        tenant_id="my-tenant"
    )
    print(result.cypher_query)

Usage (Enrichment Mode):
    from src.core.agents.cypher_code_gen_agent import cypher_enrichment_agent
    
    result = await cypher_enrichment_agent.process_api_data(
        api_data=[{"id": "user1", "status": "ACTIVE"}, ...],
        processing_context="Enrich API user data with GraphDB information",
        correlation_id="req-123"
    )
    # Returns PolarsOptimizedOutput with ID extraction + Cypher template + JOIN spec
"""

import logging
import json
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.core.okta.graph_db.schema_v2_enhanced import get_graph_schema_description
from src.config.settings import settings

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# Output Models
# ============================================================================

class CypherQueryOutput(BaseModel):
    """Structured output for Cypher query generation (Direct Mode)"""
    
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


class PolarsOptimizedOutput(BaseModel):
    """Output optimized for Polars DataFrame processing (Enrichment Mode)
    
    This model supports the high-performance Polars optimization pattern:
    1. Extract IDs from API data (JSONPath)
    2. Generate Cypher query template with $ids parameter
    3. Execute query with IN clause
    4. JOIN results with API DataFrame using Polars (13,964x faster than temp tables)
    """
    id_extraction_path: str = Field(
        ..., 
        description="JSONPath or field name to extract IDs from API data (e.g. 'id', 'profile.login', 'actor.id')"
    )
    cypher_query_template: str = Field(
        ..., 
        description="Cypher query with $user_ids or $group_ids parameter for IN clause"
    )
    api_dataframe_fields: List[str] = Field(
        ..., 
        description="Fields to keep from API data for final JOIN"
    )
    join_field: str = Field(
        ..., 
        description="Field name to join API DataFrame and GraphDB results on (e.g. 'okta_id')"
    )
    explanation: str = Field(
        ..., 
        description="Context about what this enrichment accomplishes"
    )
    estimated_records: int = Field(
        0, 
        description="Estimated number of records after enrichment"
    )
    use_polars_optimization: bool = Field(
        True, 
        description="Flag indicating this uses Polars optimization"
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
    import re
    
    query_upper = query.upper()
    
    # Dangerous operations (write operations)
    # Use word boundaries to avoid false positives (e.g., "created_at" shouldn't match "CREATE")
    dangerous_patterns = [
        r'\bCREATE\b',
        r'\bDELETE\b',
        r'\bDETACH\s+DELETE\b',
        r'\bSET\b',
        r'\bREMOVE\b',
        r'\bMERGE\b',
        r'\bDROP\b',
        r'\bALTER\b',
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, query_upper):
            match = re.search(pattern, query_upper)
            logger.warning(f"Unsafe Cypher query detected: contains '{match.group()}'")
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
    'openai:gpt-4o',
    output_type=CypherQueryOutput,
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
    model_override: Optional[str] = None
) -> CypherQueryOutput:
    """
    Generate a Cypher query from a natural language question.
    
    Args:
        question: Natural language question about the data
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
    
    output = result.output
    
    # Log the generated query BEFORE safety check (so we can see what went wrong)
    logger.info(f"📝 Generated Cypher query:\n{output.cypher_query}")
    
    # Security validation
    if not is_safe_cypher(output.cypher_query):
        logger.error(f"🚫 UNSAFE QUERY BLOCKED:\n{output.cypher_query}")
        raise ValueError(
            "Generated query contains unsafe operations (write/delete). "
            "Only read-only queries are allowed."
        )
    
    return output


async def generate_cypher_query_with_logging(
    question: str,
    model_override: Optional[str] = None
) -> CypherQueryOutput:
    """
    Generate Cypher query with detailed logging.
    
    Wrapper around generate_cypher_query that adds logging for debugging.
    
    Args:
        question: Natural language question about the data
        model_override: Optional model override
        
    Returns:
        CypherQueryOutput with generated query and metadata
    """
    logger.info(f"Generating Cypher query for: {question}")
    
    try:
        result = await generate_cypher_query(question, model_override)
        
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
                    question=question
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


# ============================================================================
# Enrichment Mode Agent (API Data → GraphDB)
# ============================================================================

class CypherEnrichmentDependencies(BaseModel):
    """Dependencies for Cypher enrichment processing"""
    api_data_sample: Any  # Flexible - let LLM handle any data type
    api_data_count: int
    processing_context: str
    flow_id: str


class CypherEnrichmentAgent:
    """Cypher enrichment agent for API data processing with Polars optimization"""
    
    def __init__(self):
        # Load base prompt
        self.base_prompt = SYSTEM_PROMPT_TEMPLATE
        
        # Load enrichment addon prompt
        enrichment_prompt_file = Path(__file__).parent / "prompts" / "cypher_api_enrichment_addon.txt"
        try:
            with open(enrichment_prompt_file, 'r', encoding='utf-8') as f:
                self.enrichment_addon = f.read()
        except FileNotFoundError:
            logger.warning(f"Enrichment prompt file not found: {enrichment_prompt_file}, using default")
            self.enrichment_addon = """
## POLARS OPTIMIZATION MODE - API DATA ENRICHMENT

**YOUR TASK**: Analyze the API data structure provided and generate PolarsOptimizedOutput for enrichment.

### CRITICAL - DATA FLATTENING AND ID EXTRACTION

**IMPORTANT**: API data is automatically **flattened** before you see it!
- Nested structures like `{"actor": {"id": "X"}}` become flattened: `{"actor_id": "X"}`
- Underscore separator is used: `actor.id` → `actor_id`, `profile.login` → `profile_login`
- Arrays are flattened: `target.0.id` → `target_0_id`

**ID Extraction Path Rules**:
- Use **flattened field names** with underscores
- Example: `"actor_id"` NOT `"actor.id"`
- Example: `"profile_login"` NOT `"profile.login"`
- Example: `"target_0_id"` NOT `"target.0.id"`

**STEP 1: Understand System Log Structure (AFTER FLATTENING)**

System Log events are flattened to:
```json
{
  "actor_id": "00u123...",                    ← User ID who performed action
  "actor_alternateId": "user@example.com",   ← User email
  "actor_type": "User",
  "actor_displayName": "John Doe",
  "target_0_type": "AppInstance",            ← What was acted upon
  "target_0_id": "0oa456...",
  "eventType": "user.session.start"
}
```

**CRITICAL**: For queries about "users who logged in" → use `"actor_id"` (the person performing the login action)
**DO NOT** use `target_*` fields for user login queries - target contains apps/authenticators, not the logged-in user!

**STEP 2: Choose the Correct Flattened Path**

For **System Log Events** (flattened):
- Users who logged in / performed action → **ALWAYS use `"actor_id"`**
- Application involved → `"target_0_displayName"` or `"target_0_id"`

For **Direct Entity APIs** (users, groups, apps - also flattened):
- ID field → `"id"`
- User login → `"profile_login"` (NOT `"profile.login"`)

### OUTPUT SPECIFICATION

Generate PolarsOptimizedOutput with these fields:

**Example for System Log → User Groups**:
```json
{
  "id_extraction_path": "actor_id",
  "cypher_query_template": "MATCH (u:User)-[:MEMBER_OF]->(g:OktaGroup) WHERE u.okta_id IN $user_ids RETURN u.okta_id, u.email, u.login, u.first_name, u.last_name, collect({group_id: g.okta_id, group_name: g.name, group_type: g.group_type}) AS groups",
  "api_dataframe_fields": ["actor_id", "actor_alternateId", "eventType", "published"],
  "join_field": "okta_id"
}
```

**Key Points**:
- `id_extraction_path`: Use **flattened field names** with underscores (e.g., `"actor_id"` for System Log users)
- `cypher_query_template`: Use parameterized query with **ONE** parameter name that matches your entity type:
  - For User queries → use `$user_ids` 
  - For Group queries → use `$group_ids`
  - For Application queries → use `$app_ids`
  - **ONLY include the ONE parameter you need** - do not include unused parameters!
- **CRITICAL**: Use the EXACT property names from the GRAPH SCHEMA above - check the schema for each node type!
- `api_dataframe_fields`: Fields from API data to include in final result
- `join_field`: The GraphDB field name to match against (usually `"okta_id"`)


This enables 13,964x performance improvement over temp tables.
"""
        
        # Get GraphDB schema for enrichment agent
        schema_description = get_graph_schema_description()
        
        # Combine prompts with schema
        full_prompt = (
            self.base_prompt + 
            "\n\n## CURRENT GRAPH SCHEMA\n\n" + schema_description +
            "\n\n" + self.enrichment_addon
        )
        
        # Create enrichment agent
        self.agent = Agent(
            'openai:gpt-4o',
            output_type=PolarsOptimizedOutput,
            system_prompt=full_prompt,
        )
    
    async def process_api_data(
        self, 
        api_data: Union[List[Dict[str, Any]], Dict[str, Any]], 
        processing_context: str, 
        correlation_id: str,
        all_step_contexts: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> PolarsOptimizedOutput:
        """
        Process API data using Polars optimization for GraphDB enrichment
        
        Args:
            api_data: API response data (list or dict)
            processing_context: Description of what enrichment is needed
            correlation_id: Request tracking ID
            all_step_contexts: Optional context from previous steps
            
        Returns:
            PolarsOptimizedOutput with ID extraction path, Cypher template, and JOIN spec
        """
        # Normalize api_data to always be a list
        if isinstance(api_data, dict):
            normalized_api_data = [api_data]
        elif isinstance(api_data, list):
            normalized_api_data = api_data
        else:
            normalized_api_data = []
            logger.warning(f"[{correlation_id}] Unexpected api_data type: {type(api_data)}, using empty list")
        
        logger.info(f"[{correlation_id}] Cypher Enrichment Agent processing {len(normalized_api_data)} records")
        logger.debug(f"[{correlation_id}] Processing context: {processing_context}")
        
        # Sample for LLM context (first 5 records)
        sample_data = normalized_api_data[:5] if normalized_api_data else []
        
        # Get tenant ID
        tenant_id = settings.tenant_id
        
        # Create dependencies
        deps = CypherEnrichmentDependencies(
            api_data_sample=sample_data,
            api_data_count=len(normalized_api_data),
            processing_context=processing_context,
            flow_id=correlation_id,
            tenant_id=tenant_id
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
1. **id_extraction_path**: JSONPath or field name to extract IDs (e.g., 'id', 'profile.login')
2. **cypher_query_template**: Cypher query with $user_ids or $group_ids parameter for IN clause
3. **api_dataframe_fields**: List of API fields to keep for final result
4. **join_field**: Field name to join on (e.g., 'okta_id')

CRITICAL: Use $user_ids or $group_ids parameter in Cypher template for IN clause!
Example: WHERE u.okta_id IN $user_ids
"""
        
        try:
            # Run agent
            result = await self.agent.run(
                user_message,
                deps=deps,
                message_history=[]
            )
            
            output = result.output
            
            logger.info(f"[{correlation_id}] ✅ Enrichment plan generated successfully")
            logger.info(f"[{correlation_id}] ID extraction: {output.id_extraction_path}")
            logger.info(f"[{correlation_id}] JOIN field: {output.join_field}")
            logger.debug(f"[{correlation_id}] Cypher template:\n{output.cypher_query_template}")
            
            return output
            
        except Exception as e:
            logger.error(f"[{correlation_id}] ❌ Enrichment planning failed: {e}")
            raise


# ============================================================================
# Global Agent Instances
# ============================================================================

# Direct mode agent (user questions → Cypher queries)
# Use generate_cypher_query() or generate_cypher_query_with_logging()

# Enrichment mode agent (API data → Cypher with Polars optimization)
cypher_enrichment_agent = CypherEnrichmentAgent()
