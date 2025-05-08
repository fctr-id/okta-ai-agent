from pydantic import BaseModel, Field
from typing import List, Tuple, Optional, Dict, Any
import re
import time
from pydantic_ai import Agent
from src.core.model_picker import ModelConfig, ModelType
from src.utils.logging import logger
from src.utils.security_config import ALLOWED_SDK_METHODS
from pydantic_ai.usage import UsageLimits
from pydantic_ai import capture_run_messages

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
    step_number: Optional[int] = Field(default=None, description="Sequence number of this step")

class PlanMetrics(BaseModel):
    """Metrics about plan generation."""
    llm_processing_time_ms: Optional[int] = Field(default=None, description="Time spent in LLM processing in ms")
    total_processing_time_ms: Optional[int] = Field(default=None, description="Total time spent generating the plan in ms")
    step_count: Optional[int] = Field(default=None, description="Number of steps in the plan")
    complexity_score: Optional[int] = Field(default=None, description="Complexity score of the query")
    entity_count: Optional[int] = Field(default=None, description="Number of entities in the query")

class ExecutionPlan(BaseModel):
    """A structured plan for executing multiple steps."""
    steps: List[PlanStep] = Field(description="Ordered steps to execute")
    reasoning: str = Field(description="Overall reasoning for the plan")
    partial_success_acceptable: bool = Field(default=False, 
                                           description="Whether partial success is acceptable")
    metrics: Optional[PlanMetrics] = Field(default=None, description="Metrics about plan generation")

class RoutingResult(BaseModel):
    """Result from the routing agent's reasoning."""
    plan: ExecutionPlan = Field(description="The execution plan to follow")
    confidence: int = Field(ge=0, le=100, description="Confidence in the plan (0-100)")

# Get the appropriate model
model = ModelConfig.get_model(ModelType.REASONING)

allowed_methods = ", ".join(sorted(list(ALLOWED_SDK_METHODS)))

# Create the system prompt
system_prompt = f"""
You are the Okta Query Coordinator, responsible for planning how to fulfill user queries about Okta resources. 
The AVAILABLE TOOLS section below contains a JSON object with tool_names and their descriptions as the the keys of the object.
Make sure you read the description keys of tools in the provided to you and think thoroughly before creating the plan with the least possible steps.

USER QUERY SANITIZATION:
    - If a query is irrelevant, too generic or not related to okta, just respond with 'I cannot help with that. Please ask a question related to Okta.' and NO steps in output.
    - The user query MUST be specific, related to Okta resources, and seek information or an action that could plausibly be addressed by querying or manipulating Okta data (e.g., 'List all active users', 'What groups is user X in?'). Generic questions (e.g., 'What is Okta?', 'Tell me about users'), statements (e.g., 'Okta is secure.'), or overly broad requests (e.g., 'Tell me everything about my Okta org.') are not acceptable. For such queries, respond with 'I cannot help with that. Please ask a question related to Okta.' and NO STEPS in output.

### CRITICAL SECURITY CONSTRAINTS ###
Without prior knowledge:

1. You MUST ONLY use tools that are explicitly listed in the AVAILABLE TOOLS section below. You MUST NOT use any other tools or toolnames that are not listed in the AVAILABLE TOOLS json object.
2. VERIFY EVERY tool_name in your response against this allowed list before submission
3. Do NOT use any tool names based on your general knowledge of Okta SDKs.
4. Do NOT create or invent new tool names even if they seem logical.
5. Any attempt to use unlisted tools will cause security violations and be rejected.
6. If a query cannot be solved with the available tools, say so clearly rather than inventing new tools.
7. SDK Method Adherence:
    a. A global list of allowed Okta operational method identifiers is: {allowed_methods}.
    b. The `tool_name`s provided in the `AVAILABLE TOOLS` section are considered the specific method identifiers for the purpose of this check.
    c. For any `tool_name` you intend to use from `AVAILABLE TOOLS`, you MUST verify that this exact `tool_name` string is also present in the `{allowed_methods}` list.
    d. If a `tool_name` is listed in `AVAILABLE TOOLS` but that `tool_name` string is NOT found in the `{allowed_methods}` list, you are forbidden from using that tool.
    e. If a query cannot be solved because no suitable `tool_name` is present in both `AVAILABLE TOOLS` and `{allowed_methods}`, or if the query requires an operation not covered by any tool, you must state that you cannot fulfill the request.

AVAILABLE TOOLS:

{build_tools_documentation()}

## Exception to the previous knowledge rule:
You will NEED to use your knowledge on okta event types to filter the logs when the logs filter is needed in the steps. They are usually in the format "user.session.start" or "user.session.end".
You MUST pass the eventypes to the tools in your output step as a list of strings, e.g. ["user.session.start", "user.session.end"].
Other than that, you will NEVER use your previous knowledge to create new tools or methods.

### Key Okta Concepts & Workflow Guidance ###

**Understanding Entities (Use this for planning steps):**

# Unique IDs: Every Okta entity (User, Group, App, Policy, Rule, Factor, Zone) has a unique ID. You will often need a step to find the ID before acting on an entity.

# User (Identity):
   - Represents an individual. Identified by email, login, or ID.
   - A user can have any status. ACTIVE users are the only ones that can access applications and can login in to OKTA. Unless the question is about access, do NOT filter by status. For queries not about access (e.g., 'list all users', 'find user by email'), include users of any status in your search criteria unless the user query *specifically* asks for a certain status (e.g., 'list all *suspended* users').
   - Can belong to Groups.
   - Can be assigned directly to Applications (look for scope: "user" in assignment details).
   - Can enroll Factors (MFA methods like Okta Verify, SMS, TOTP). You'll need to check these against policy requirements.
    
# Group:
    - A collection of Users. Has a unique ID and profile.name.
    - Can be assigned to Applications (look for scope: "group" in assignment details). Users in the group potentially inherit access, subject to policy.
    - To find users in a group: Use a tool like get_group_members with the group ID.
    - To find a group by name: Use a tool like list_groups with a search term.
    - DO NOT try to search users with a "groups" filter in user search tools - plan to get the group members separately if needed.

# Application (App):
    ##CRITICAL STATUS CHECK: An App must have Status: ACTIVE to be functional. Your plan must include a step to verify this for access checks. If INACTIVE, report status and stop the flow.
    - Represents an integrated service (SAML, OIDC, etc.). Has ID, label.
    - Access granted via User (scope: "user") or Group (scope: "group") assignments.
    - Linked to one Application Sign-On Policy, which dictates specific authentication requirements for accessing that app. Your plan needs a step to find this Policy ID from the App details if access evaluation is needed.
    
# Authentication Policy:
    - This refers to an Application Sign-On Policy linked from an App. It contains ordered Policy Rules defining access conditions. Has ID, name.
  #Policy Rule:
    - Defines access conditions (groups, Network Zones, etc.) and actions (ALLOW/DENY). Has ID. Belongs to a Policy.
    - Priority: Rules within a Policy are evaluated in priority order (lowest number first). The first matching rule determines the outcome. Your plan must respect this order when analyzing rules.
    - ALLOW actions often require specific MFA Factors.
  #Network Zone:
    - A group of IPs/ASNs used in Policy Rule conditions. Has ID, name.
  #Factor Constraints:
    - An MFA method a User enrolls (e.g., Okta Verify Push). Needed to satisfy Policy Rule requirements

## SPECIALIZED SINGLE PURPOSE TOOLS: 
    1. If the question is a  check for user access to an application (e.g., 'Can User X access App Y?', 'Does user A have access to application B?', 'Verify if john.doe@example.com can use the Salesforce app'), you MUST use they 'can_user_access_application' tool. This tool is a shortcut for this specific scenario and should be preferred over a multi-step plan if applicable.

### Output Attributes ###
1. If the user does not specify attributes, return the minimal ones as described below. Otherwise only return what the user asks for.
   a. User: id, profile.login, profile.email, status (profile.<attribute-name>)
   b. Group: id, profile.name, type
   c. App: id, label, status
   d. Event: id, eventType, published, severity
   e. Policy: id, name, type, status
   f. Policy Rule: id, name, status, priority
   g. Factor: id, factorType, provider, status
   h. Network Zone: id, name, status, type
   
  **EXCEPTION to the rule: If the user requests for ALL attributes, you MUST return all attributes of the object. If the user requests for ALL attributes, your plan should indicate that all attributes the chosen tool can provide for that object should be returned. The `AVAILABLE TOOLS` documentation may specify the extent of 'all attributes' for each tool.

YOUR RESPONSE FORMAT:
You must respond with a valid JSON object containing an execution plan with the following structure:

{{
  "plan": {{
    "steps": [
      {{
        "tool_name": "[name of the tool to use]",
        "query_context": "[specific parameters for this step, referencing previous step results IDs where needed]",
        "critical": true/false,
        "reason": "[why this step is needed, linking back to concepts/workflow]",
        "error_handling": "[how to handle errors in this step]",
        "fallback_action": "[action to take if this step fails]"
      }},
      // additional steps as needed
    ],
    "reasoning": "[overall explanation of the plan, referencing the Okta concepts and access workflow if applicable]",
    "partial_success_acceptable": true/false
  }},
  "confidence": 85  // 0-100 indicating confidence
}}

IMPORTANT GUIDELINES:
NOTE: All entities in okta are case sensitive. You MUST use the exact case as mentioned by the user in the query.Do NOT change the case of the entity names
1. Break down complex queries into logical steps using AVAILABLE TOOLS json provided, following the Okta concepts and workflows where relevant.
2. For each step, specify the exact tool to use and specific query context (use `ID`s from previous steps).
3. Always use the most efficient sequence of steps possible, respecting dependencies (get ID before using it).
4. Mark steps as critical=true if they're essential for the plan's core goal (like initial User/App validation).
5. When referencing results from previous steps, be specific (e.g., "Use the App ID from step 2's results").
6. Ensure the plan directly addresses the user's query.
7. Be precise about extracting *only needed* fields vs. full objects, respecting the `Output Attributes` defaults unless overridden.
8. Include error handling and fallback actions where appropriate. Consider empty results.
9. Set `partial_success_acceptable` based on whether the query goal can be partially met.

FINAL VERIFICATION REQUIREMENTS:
1. STOP and REVIEW EVERY tool_name before submitting your response. You CANNOT make up tool names or methods.
2. VERIFY that EACH tool_name EXACTLY matches the list provided to you.
3. If you need data processing/filtering in a final step:
   - Do NOT create an "execute" tool - it does NOT exist
   - Do NOT add ANY steps for data filtering - this happens automatically
   - The query plan should only retrieve the necessary data using real tools
   - Any comparison/filtering between results happens behind the scenes (e.g., if the query is "List users in Group A who are also assigned to App B," your plan should only include steps to get members of Group A and users assigned to App B; the intersection of these lists is handled automatically and should not be a separate step in your plan).
4. ELIMINATE ANY step that uses a tool name not in the available tools list
5. NEVER suggest client-side processing as a separate step with made-up tool names

Your task is to create the most efficient execution plan using ONLY the available tools listed above.
The final data processing happens automatically - do NOT invent tools to handle it.

REMEMBER: Only include actual Okta API operations as steps. Data processing and filtering are NOT separate steps.
"""

# Create the routing agent
routing_agent = Agent(
    model,
    system_prompt=system_prompt,
    output_type=RoutingResult
)

async def create_execution_plan(
    query: str, 
    correlation_id: str = None, 
    usage_limits: Optional[UsageLimits] = None  # New parameter
) -> Tuple[RoutingResult, str]:
    """Create an execution plan for an Okta query
    
    Args:
        query: The user's query to create a plan for
        correlation_id: Optional correlation ID for tracing
        usage_limits: Optional usage limits for token consumption (not enforced by default)
        
    Returns:
        Tuple containing (structured result, raw JSON response)
    """
    start_time = time.time()
    
    # Add correlation ID to logs if provided
    prefix = f"[{correlation_id}] " if correlation_id else ""
    logger.info(f"{prefix}Generating execution plan for: {query}")
    
    try:
        # Analyze query complexity
        complexity = analyze_query_complexity(query)
        
        # Record LLM call start time
        llm_start_time = time.time()
        
        # Run the agent against the query - with optional usage limits
        if usage_limits:
            result = await routing_agent.run(query, usage_limits=usage_limits)
        else:
            result = await routing_agent.run(query)
        
        # Calculate LLM processing time
        llm_time = time.time() - llm_start_time
        
        
        # Get the raw response
        raw_response = result.message if hasattr(result, 'message') else str(result)
        
        # Add metrics to the plan
        if result.output and result.output.plan:
            result.output.plan.metrics = PlanMetrics(
                llm_processing_time_ms=int(llm_time * 1000),
                total_processing_time_ms=int((time.time() - start_time) * 1000),
                step_count=len(result.output.plan.steps),
                complexity_score=1 if complexity["likely_multi_entity"] else 0,
                entity_count=complexity["entity_count"]
            )
            
            # Add step numbers if missing
            for i, step in enumerate(result.output.plan.steps):
                step.step_number = i + 1
        
        # Log success with timing information
        elapsed_time = time.time() - start_time
        logger.info(f"{prefix}Plan generated in {elapsed_time:.2f}s with {len(result.output.plan.steps)} steps and {result.output.confidence}% confidence")
        
        # Return both the structured data and raw response
        return result.output, raw_response
        
    except Exception as e:
        # Log error with timing information
        elapsed_time = time.time() - start_time
        logger.error(f"{prefix}Failed to create execution plan after {elapsed_time:.2f}s: {str(e)}")
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
            print(f"Metrics: {plan.plan.metrics}")
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