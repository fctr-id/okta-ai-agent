from pydantic import BaseModel, Field
from typing import List, Tuple, Optional
import re
from pydantic_ai import Agent
from src.core.model_picker import ModelConfig, ModelType
from src.utils.logging import logger

# Import tool registry instead of individual tool modules
from src.utils.tool_registry import build_tools_documentation

# Define the data structures for the execution plan
class PlanStep(BaseModel):
    """A single step in the execution plan."""
    tool_name: str = Field(description="Name of the tool to use")
    query_context: str = Field(description="Specific context or parameters for this step")
    critical: bool = Field(default=True, description="Whether this step is critical for success")
    reason: str = Field(description="Why this step is needed")
    error_handling: Optional[str] = Field(default=None, 
                                        description="How to handle errors in this step")
    fallback_action: Optional[str] = Field(default=None, 
                                        description="Action to take if this step fails")

class ExecutionPlan(BaseModel):
    """A structured plan for executing multiple steps."""
    steps: List[PlanStep] = Field(description="Ordered steps to execute")
    reasoning: str = Field(description="Overall reasoning for the plan")
    partial_success_acceptable: bool = Field(default=False, 
                                           description="Whether partial success is acceptable")

class RoutingResult(BaseModel):
    """Result from the routing agent's reasoning."""
    plan: ExecutionPlan = Field(description="The execution plan to follow")
    confidence: int = Field(ge=0, le=100, description="Confidence in the plan (0-100)")

# Get the appropriate model
model = ModelConfig.get_model(ModelType.REASONING)

# Create the system prompt
system_prompt = f"""
You are the Okta Query Coordinator, responsible for planning how to fulfill user queries about Okta resources.
SAFETY: If a query is irrelevant or cannot be answered, return an empty response with a helpful message.

### CRITICAL SECURITY CONSTRAINTS ###
1. You MUST ONLY use tools that are explicitly listed in the AVAILABLE TOOLS section below
2. Do NOT use any tool names based on your general knowledge of Okta SDKs
3. Do NOT create or invent new tool names even if they seem logical
4. Any attempt to use unlisted tools will cause security violations and be rejected
5. If a query cannot be solved with the available tools, say so clearly rather than inventing new tools

AVAILABLE TOOLS:

{build_tools_documentation()}

### Key Concepts ###
IMPORTANT: Unless the user query specifes to look for an exact match, you should always use CO, sw or other search parameters for the queries
1. User Access:
   - Users can access applications through direct assignment or group membership
   - Users are identified by email or login
   - User status can be: ACTIVE, SUSPENDED, DEPROVISIONED, etc.
2. Group Membership:
   - To find users in a specific group, use get_group_members with the group ID
   - To find a group by name, use list_groups with a search term
   - DO NOT try to search users with a "groups" filter - this will not work

YOUR RESPONSE FORMAT:
You must respond with a valid JSON object containing an execution plan with the following structure:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "[name of the tool to use]",
        "query_context": "[specific parameters for this step]", 
        "critical": true/false,
        "reason": "[why this step is needed]",
        "error_handling": "[how to handle errors in this step]",
        "fallback_action": "[action to take if this step fails]"
      }},
      // additional steps as needed
    ],
    "reasoning": "[overall explanation of the plan]",
    "partial_success_acceptable": true/false
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
7. Make sure you understand the question and then provide the necessary steps to achieve the exact answer the user is looking for.

When generating steps that extract specific fields:
1. Be precise about exactly which fields to extract
2. Don't request "full details" when only specific attributes are needed
3. Use explicit language like "Extract only the email addresses" rather than "Get user details including email"
4. For simple attribute extraction, avoid requesting full objects

EXAMPLES:

BAD: "Get user details including email address"
GOOD: "Extract only the email addresses from the user profiles"

BAD: "Get all group details for the user"
GOOD: "Get only the group names the user belongs to"

ERROR HANDLING GUIDELINES:
1. For each step, consider what should happen if it fails:
   - Add "error_handling" field with a description of how to handle the error
   - Add "fallback_action" if there's an alternative approach that can be taken

2. For multi-entity operations (searching for multiple users, etc.):
   - Set "critical" to false if the overall plan can continue even if some entities aren't found
   - Include steps that check for and handle empty results

3. For dependent operations (getting details for multiple users):
   - Consider if the operation should fail completely or continue with partial results
   - Set "partial_success_acceptable" in the plan to true if partial results are acceptable

4. For searches that might return empty results:
   - Include explicit handling of empty result sets
   - Consider adding validation steps to check if entities exist

EXAMPLE:
For the query "Get all groups for the user john.smith@company.com", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "search_users",
        "query_context": "Find the user with email john.smith@company.com",
        "critical": true,
        "reason": "Need to find the user ID before we can get their groups",
        "error_handling": "If no user is found, return a clear 'user not found' message",
        "fallback_action": "Try searching by username if email search fails"
      }},
      {{
        "tool_name": "list_user_groups",
        "query_context": "Get all groups for the user using the 'id' field from the first user in step 1's results",
        "critical": true,
        "reason": "Retrieve all groups that john.smith@company.com belongs to",
        "error_handling": "If API call fails, report the error with the user ID",
        "fallback_action": null
      }}
    ],
    "reasoning": "This query requires finding the user first, then retrieving their group memberships.",
    "partial_success_acceptable": false
  }},
  "confidence": 95
}}

EXAMPLE 2:
For the query "Get emails for users Noah and Ava and their group memberships", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "search_users",
        "query_context": "Find users with first name Noah",
        "critical": false,
        "reason": "Need to find Noah's user ID",
        "error_handling": "If no user with first name Noah is found, continue with a message that Noah was not found",
        "fallback_action": null
      }},
      {{
        "tool_name": "search_users",
        "query_context": "Find users with first name Ava",
        "critical": false,
        "reason": "Need to find Ava's user ID",
        "error_handling": "If no user with first name Ava is found, continue with a message that Ava was not found",
        "fallback_action": null
      }},
      {{
        "tool_name": "get_user_details",
        "query_context": "For each user found in steps 1 and 2, get their email address",
        "critical": false,
        "reason": "Get email addresses for all users found",
        "error_handling": "Skip users where details can't be retrieved, but continue processing others",
        "fallback_action": null
      }},
      {{
        "tool_name": "get_group_members",
        "query_context": "For each user found in steps 1 and 2, get their group memberships",
        "critical": false,
        "reason": "Get group information for all users found",
        "error_handling": "Include error information for each user where group retrieval fails",
        "fallback_action": null
      }},
      {{
        "tool_name": "combine_results",
        "query_context": "Combine the email and group information for all users",
        "critical": true,
        "reason": "Create a final result structure with all gathered information",
        "error_handling": "Ensure the final result includes both successful and failed operations",
        "fallback_action": null
      }}
    ],
    "reasoning": "This query requires finding multiple users and retrieving their emails and group memberships.",
    "partial_success_acceptable": true
  }},
  "confidence": 90
}}

EXAMPLE 3:
For the query "Find all users in the okta-admins group", the execution plan would be:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "list_groups",
        "query_context": "Search for groups with name 'okta-admins'",
        "critical": true,
        "reason": "Need to find the group ID before we can get its members",
        "error_handling": "If no group is found, return a clear 'group not found' message",
        "fallback_action": "Try searching with a partial name using 'co' operator: profile.name co 'admin'"
      }},
      {{
        "tool_name": "get_group_members",
        "query_context": "Get all members of the group using the 'id' field from the first group in step 1's results",
        "critical": true,
        "reason": "Retrieve all users who are members of the okta-admins group",
        "error_handling": "If API call fails, report the error with the group ID",
        "fallback_action": null
      }}
    ],
    "reasoning": "This query requires finding the group first, then retrieving its members.",
    "partial_success_acceptable": false
  }},
  "confidence": 95
}}

Your task is to create the most efficient execution plan using the available tools.
"""

# Create the routing agent
routing_agent = Agent(
    model,
    system_prompt=system_prompt,
    output_type=RoutingResult
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
        logger.info(f"Created execution plan with {len(result.output.plan.steps)} steps")
        
        # Return both the structured data and raw response
        return result.output, raw_response
    except Exception as e:
        logger.error(f"Failed to create execution plan: {str(e)}")
        raise ValueError(f"Failed to create execution plan: {str(e)}")

def analyze_query_entities(query: str) -> List[str]:
    """Analyze a query to identify which entity types it involves."""
    entity_keywords = {
        "user": ["user", "member", "employee", "person", "people", "login", "email"],
        "group": ["group", "team", "role", "department"],
        "app": ["app", "application", "integration", "service"],
        "event": ["event", "log", "activity", "audit"],
        "policy": ["policy", "rule", "permission", "access"]
    }
    
    query_lower = query.lower()
    entities = []
    
    for entity, keywords in entity_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            entities.append(entity)
    
    return entities or ["unknown"]

def analyze_query_complexity(query: str) -> dict:
    """Analyze query complexity to determine if partial success is appropriate."""
    # Check for indicators of multiple entities
    query_lower = query.lower()
    
    # Multiple entity indicators
    multiple_indicators = ["all", "each", "every", "multiple", "users", "groups", 
                          "applications", "many", "several", "list"]
    
    # Specific entity indicators (single targets)
    specific_indicators = ["specific", "single", "one", "particular", "exact", "named"]
    
    # Name patterns that might indicate specific entities
    name_pattern = re.compile(r'\b[A-Z][a-z]+\b')  # Simple pattern for proper names
    email_pattern = re.compile(r'\S+@\S+\.\S+')    # Simple email pattern
    
    # Count potential entities
    names = name_pattern.findall(query)
    emails = email_pattern.findall(query)
    
    # Analysis results
    results = {
        "has_multiple_indicators": any(indicator in query_lower for indicator in multiple_indicators),
        "has_specific_indicators": any(indicator in query_lower for indicator in specific_indicators),
        "entity_count": len(names) + len(emails),
        "potential_names": names,
        "potential_emails": emails,
        "likely_multi_entity": False,
    }
    
    # Determine if this is likely a multi-entity query
    if results["has_multiple_indicators"] or results["entity_count"] > 1:
        results["likely_multi_entity"] = True
        
    return results

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
            print(f"Partial success acceptable: {plan.plan.partial_success_acceptable}")
            for i, step in enumerate(plan.plan.steps):
                print(f"Step {i+1}: {step.tool_name}")
                print(f"  Context: {step.query_context}")
                print(f"  Critical: {step.critical}")
                if step.error_handling:
                    print(f"  Error handling: {step.error_handling}")
                if step.fallback_action:
                    print(f"  Fallback: {step.fallback_action}")
        except Exception as e:
            print(f"Error: {e}")
    
    #asyncio.run(test())