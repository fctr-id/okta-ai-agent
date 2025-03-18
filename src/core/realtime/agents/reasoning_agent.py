from pydantic import BaseModel, Field
from typing import List, Tuple
from pydantic_ai import Agent
from src.core.model_picker import ModelConfig, ModelType
from src.utils.logging import logger

# Import tool definitions
from src.core.realtime.tools.user_tools import get_all_user_tools

# Define the data structures for the execution plan
class PlanStep(BaseModel):
    """A single step in the execution plan."""
    tool_name: str = Field(description="Name of the tool to use")
    query_context: str = Field(description="Specific context or parameters for this step")
    critical: bool = Field(default=True, description="Whether this step is critical for success")
    reason: str = Field(description="Why this step is needed")

class ExecutionPlan(BaseModel):
    """A structured plan for executing multiple steps."""
    steps: List[PlanStep] = Field(description="Ordered steps to execute")
    reasoning: str = Field(description="Overall reasoning for the plan")

class RoutingResult(BaseModel):
    """Result from the routing agent's reasoning."""
    plan: ExecutionPlan = Field(description="The execution plan to follow")
    confidence: int = Field(ge=0, le=100, description="Confidence in the plan (0-100)")

# Get the appropriate model
model = ModelConfig.get_model(ModelType.REASONING)

def build_tools_documentation():
    """Build documentation for all available tools."""
    tools_docs = ""
    
    # Get all user tools
    user_tools = get_all_user_tools()
    
    # User Tools section
    tools_docs += "User Tools:\n"
    for tool in user_tools:
        tools_docs += f"- {tool.name}: {tool.description}\n"
    
    return tools_docs

# Create the system prompt
system_prompt = f"""
You are the Okta Query Coordinator, responsible for planning how to fulfill user queries about Okta resources.

AVAILABLE TOOLS:

{build_tools_documentation()}

### Key Concepts ###

1. User Access:
   - Users can access applications through direct assignment or group membership
   - Users are identified by email or login
   - User status can be: ACTIVE, SUSPENDED, DEPROVISIONED, etc.

YOUR RESPONSE FORMAT:
You must respond with a valid JSON object containing an execution plan with the following structure:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "[name of the tool to use]",
        "query_context": "[specific parameters for this step]", 
        "critical": true/false,
        "reason": "[why this step is needed]"
      }},
      // additional steps as needed
    ],
    "reasoning": "[overall explanation of the plan]"
  }},
  "confidence": 85  // 0-100 indicating confidence
}}

IMPORTANT GUIDELINES:
1. Break down complex queries into logical steps using available tools
2. For each step, specify the exact tool to use and specific query context
3. Always use the most efficient sequence of steps possible
4. Mark steps as critical=true if they're essential for the plan to succeed
5. When a tool requires an ID, you must include a previous step to retrieve that ID first
6. When referencing results from previous steps, be specific about which field to use (e.g., "Get user with ID from the first user's id field in step 1's results")
7. Make sure you understand the question and then provide the necessary steps to achive the exact answer the user is looking for.

EXAMPLE:
For the query "Get all groups for the user john.smith@company.com", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "search_users",
        "query_context": "Find the user with email john.smith@company.com",
        "critical": true,
        "reason": "Need to find the user ID before we can get their groups"
      }},
      {{
        "tool_name": "list_user_groups",
        "query_context": "Get all groups for the user using the 'id' field from the first user in step 1's results",
        "critical": true,
        "reason": "Retrieve all groups that john.smith@company.com belongs to"
      }}
    ],
    "reasoning": "This query requires finding the user first, then retrieving their group memberships."
  }},
  "confidence": 95
}}

Your task is to create the most efficient execution plan using the available tools.
"""

# Create the routing agent
routing_agent = Agent(
    model,
    system_prompt=system_prompt,
    result_type=RoutingResult
)

async def create_execution_plan(query: str) -> Tuple[RoutingResult, str]:
    """Create an execution plan for an Okta query
    
    Returns:
        Tuple containing (structured result, raw JSON response)
    """
    try:
        # Run the agent against the query
        result = await routing_agent.run(query)
        
        # Get the raw response from result.raw (the full raw LLM response in the example)
        raw_response = result.message if hasattr(result, 'message') else str(result)
        
        # Log some info about the result
        logger.info(f"Created execution plan with {len(result.data.plan.steps)} steps")
        
        # Return both the structured data and raw response
        return result.data, raw_response
    except Exception as e:
        logger.error(f"Failed to create execution plan: {str(e)}")
        raise ValueError(f"Failed to create execution plan: {str(e)}")

# For interactive testing
if __name__ == "__main__":
    import asyncio
    
    async def test():
        query = "Get all groups for the user john.smith@company.com"
        try:
            plan, raw = await create_execution_plan(query)
            print(f"Raw response: {raw}")
            print(f"Plan confidence: {plan.confidence}%")
            print(f"Reasoning: {plan.plan.reasoning}")
            for i, step in enumerate(plan.plan.steps):
                print(f"Step {i+1}: {step.tool_name}")
                print(f"  Context: {step.query_context}")
        except Exception as e:
            print(f"Error: {e}")
    
    #asyncio.run(test())