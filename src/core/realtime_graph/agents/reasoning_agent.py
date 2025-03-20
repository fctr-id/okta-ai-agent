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

### Special Operations ###

1. ForEach: Used to process each item in a collection
   - Required parameters:
     - "items": Reference to a collection (e.g., "state.users_list")
     - "operation": The operation to execute for each item, using a standard format:
       - Simple string format: "operation_name" 
       - OR object format: {{
         "type": "operation_name",
         "params": {{ parameter object }},
         "description": "Description of what this operation does"
       }}
     - "params": Parameters for the operation, use "item.attribute" for item properties
     - "output": Variable name to store results (e.g., "user_details_list")

2. JoinResults: Used to combine multiple results
   - Required parameters:
     - "results": Reference to the results collection (e.g., "state.operation_results")
     - "join_type": Type of join ("merge", "extract", etc.)
     - "key": When extracting, the field to extract (e.g., "profile.email")

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
6. When referencing results from previous steps, be specific about which field to use
7. When using ForEach, always follow the exact parameter structure defined above
8. Make sure you understand the question and provide the necessary steps
9. Always specify an "output" parameter for ForEach operations to store results
10. Always use "join_results" to extract specific fields like emails or usernames

EXAMPLE 1:
For the query "Get all groups for the user john.smith@company.com", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "search_users",
        "query_context": {{
          "search_query": "profile.email eq \\"john.smith@company.com\\""
        }},
        "critical": true,
        "reason": "Need to find the user ID before we can get their groups"
      }},
      {{
        "tool_name": "get_user_groups",
        "query_context": {{
          "user_id": "state.users_list[0].id"
        }},
        "critical": true,
        "reason": "Retrieve all groups that john.smith@company.com belongs to"
      }}
    ],
    "reasoning": "This query requires finding the user first, then retrieving their group memberships."
  }},
  "confidence": 95
}}

EXAMPLE 2:
For the query "Get email addresses of users named Noah and Ava", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "search_users",
        "query_context": {{
          "search_query": "profile.firstName eq \\"Noah\\" or profile.firstName eq \\"Ava\\""
        }},
        "critical": true,
        "reason": "Need to find users matching the specified first names"
      }},
      {{
        "tool_name": "for_each",
        "query_context": {{
          "items": "state.users_list",
          "operation": {{
            "type": "get_user_details",
            "params": {{
              "user_id": "item.id"
            }},
            "description": "Get detailed information for each user"
          }},
          "output": "user_details_list"
        }},
        "critical": true,
        "reason": "Retrieve detailed information for each user found"
      }},
      {{
        "tool_name": "join_results",
        "query_context": {{
          "results": "state.user_details_list",
          "join_type": "extract",
          "key": "profile.email"
        }},
        "critical": true,
        "reason": "Extract email addresses from the user details"
      }}
    ],
    "reasoning": "This plan searches for users with the given first names, then retrieves detailed information for each user, and finally extracts their email addresses."
  }},
  "confidence": 90
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