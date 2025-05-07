from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import re
import logging
from pydantic_ai import Agent
from src.core.model_picker import ModelConfig, ModelType
from src.utils.security_config import (
    ALLOWED_SDK_METHODS, ALLOWED_UTILITY_METHODS,
    ALLOWED_MODULES, DANGEROUS_PATTERNS
)
# Add import for tool registry
from src.utils.tool_registry import get_tool_prompt

logger = logging.getLogger(__name__)

class CodeGenerationResult(BaseModel):
    """Result of code generation for a workflow."""
    step_codes: List[str] = Field(description="Generated code for each step")
    raw_response: str = Field(description="Raw response from the coding agent")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

class CodingAgent:
    """
    Agent responsible for generating Okta SDK code for workflows.
    """
    
    def __init__(self):
        """Initialize the coding agent with the appropriate model."""
        # Get the coding model
        model = ModelConfig.get_model(ModelType.CODING)
        
        # Create the agent
        self.agent = Agent(
            model,
            system_prompt="You are an expert at writing Python code for Okta SDK operations.",
            retries=2
            # No result_type as we'll parse the output manually
        )
        
    async def generate_workflow_code(self, plan, tool_docs: List[str] = None, flow_id: str = "unknown") -> CodeGenerationResult:
        """
        Generate code for all steps in a workflow.
        
        Args:
            plan: The execution plan with steps
            tool_docs: Documentation for each tool in the plan (can be None when using tool registry)
            flow_id: Unique identifier for the current flow/conversation
            
        Returns:
            CodeGenerationResult with code for each step
        """
        # If tool_docs is not provided, fetch them from the registry
        if tool_docs is None:
            tool_docs = []
            for step in plan.steps:
                tool_doc = get_tool_prompt(step.tool_name)
                if tool_doc:
                    tool_docs.append(tool_doc)
                else:
                    logger.warning(f"[FLOW:{flow_id}] Documentation not found for tool: {step.tool_name}")
                    tool_docs.append(f"# Documentation not available for {step.tool_name}")

        # Ensure we have a doc for each step
        while len(tool_docs) < len(plan.steps):
            missing_index = len(tool_docs)
            missing_tool = plan.steps[missing_index].tool_name if missing_index < len(plan.steps) else "unknown"
            tool_docs.append(f"# Documentation not available for {missing_tool}")
            
        # Build the prompt
        prompt = self._build_workflow_prompt(plan, tool_docs)
        
        # Generate code
        logger.info(f"[FLOW:{flow_id}] Generating code for {len(plan.steps)} workflow steps")
        result = await self.agent.run(prompt)
        logger.debug(f"[FLOW:{flow_id}] LLM response received")
        
        # Extract the message content
        if hasattr(result, 'message'):
            response_text = result.message
        else:
            response_text = result.output if hasattr(result, 'output') else str(result)
        
        # Extract code blocks for each step
        step_codes = self._extract_step_codes(response_text, len(plan.steps))
        
        # Log debug information
        logger.debug(f"[FLOW:{flow_id}] Generated {len(step_codes)} code blocks")
        for i, code in enumerate(step_codes):
            logger.debug(f"[FLOW:{flow_id}] Step {i+1} code preview: {code[:100]}...")
        
        return CodeGenerationResult(
            step_codes=step_codes,
            raw_response=response_text,
            metadata={
                "steps_total": len(plan.steps),
                "flow_id": flow_id
            }
        )
        
    def _build_workflow_prompt(self, plan, tool_docs: List[str]) -> str:
        """Build a prompt that will generate code for all steps in the workflow."""
        steps_description = []
        
        for i, (step, doc) in enumerate(zip(plan.steps, tool_docs)):
            steps_description.append(f"""
            STEP {i+1}: {step.tool_name}
            Description: {step.query_context}
            Tool Documentation:
            {doc}
            """)
        
        steps_text = "\n".join(steps_description)
        
        # Format the allowed methods for the prompt
        sdk_methods = ", ".join(sorted(list(ALLOWED_SDK_METHODS)))
        utility_methods = ", ".join(sorted(list(ALLOWED_UTILITY_METHODS)))
        
        return f"""
        You are an AI assistant tasked with generating Python code for Okta SDK operations. You must adhere strictly to all constraints and instructions provided. Your primary goal is to produce clean, robust, and directly executable Python code snippets for multi-step Okta workflows.

        ## Core Persona & Knowledge Constraint ##
        You are an expert at writing Python code specifically for Okta SDK operations, with a strong emphasis on robust error handling as defined herein.
        However, when it comes to Okta SDK functions themselves: **You must operate as if you have no prior knowledge of Okta functions beyond what is explicitly provided in the `AVAILABLE TOOLS` documentation for this session.** Do not assume the existence or behavior of any Okta function not listed or documented there.

        ## CRITICAL: Adherence to Tool Documentation and SDK Call Structure ##
        *   You MUST generate code for SDK calls based **EXACTLY on the structure shown in the relevant tool's 'Example Usage' snippet** (found under its '## Example Usage' section).
        *   While the *core SDK call* follows the example, you **MUST integrate all other requirements from this prompt** (e.g., error handling, specific data extraction, variable usage from previous steps, no comments) into the code generated for each step.
        *   Make SURE you read the tool documentation carefully before generating code for any SDK call.

        ## CRITICAL SECURITY CONSTRAINTS (Tool Usage) ##
        1.  You MUST ONLY use tools (Okta SDK methods) that are explicitly listed in the `AVAILABLE TOOLS` section.
        2.  Do NOT use any tool names based on your general knowledge of Okta SDKs; rely SOLELY on the provided list.
        3.  Do NOT create or invent new tool names, even if they seem logical extensions of existing ones.
        4.  Any attempt to use unlisted tools will be considered a security violation and will be rejected.
        5.  If a user's query cannot be solved with the available tools, you MUST state this clearly rather than attempting to invent or use unlisted tools.

        ## WORKFLOW SPECIFICATION (Provided by User/System) ##
        *   **WORKFLOW OVERVIEW:** {plan.reasoning}
        *   **THE STEPS:** {steps_text}
        *   **AVAILABLE OKTA SDK METHODS:** {sdk_methods}
        *   **AVAILABLE PYTHON UTILITY METHODS:** {utility_methods}

        ## MULTI-STEP CODE GENERATION RULES ##
        1.  Generate separate, distinct code blocks for EACH step.
        2.  Mark each code block with `<STEP-N>` (e.g., `<STEP-1>`) and ensure it ends with `</STEP-N>` (e.g., `</STEP-1>`).
        3.  Each step's code block MUST explicitly `return` its final result.
        4.  Variables defined in earlier steps can be directly accessed by name in later steps.
        5.  NEVER use placeholder values like `"your_group_id_here"`. Always extract actual values from the results of previous steps.
        6.  When using IDs or other data from previous steps, explicitly extract them (e.g., `group_id = result_from_step_1[0]["id"]` or `user_email = previous_user_data["profile"]["email"]`).
        7.  Before accessing properties or elements of results from previous steps, ALWAYS check if the result is empty or indicates an error to prevent runtime exceptions.

        ## PYTHON CODE STYLE & FORMATTING ##
        1.  **ABSOLUTELY NO COMMENTS OR DOCSTRINGS:** Do NOT include any comments (e.g., `# This is a comment`) or docstrings (e.g., `\"\"\"This is a docstring\"\"\"`) in the generated code. This applies to imports, function definitions (if any were allowed internally, which they are not at the top level of a step), and all lines of code.
        2.  **Root Indentation:** All code within a step block must start at the root indentation level (no initial global indent for the entire block).
        3.  **No Outermost Wrappers:** Do not define functions (`def my_func(): ...`) or wrap the entire content of a `<STEP-N>` block in a single top-level `try...except` block. However, `try-except` blocks *within* the step, around specific operations, ARE required for robust error handling as specified below.
        4.  **No Logging:** Do not use Python's `logging` module functions directly (e.g., `logging.info`, `logging.error`).
        5.  **Valid Python:** Ensure all generated code is valid Python syntax that can be executed directly.
        6.  **Case Sensitivity:** Do NOT change the case of entity or label names (like application or group names) as provided in the query or step descriptions. Okta operations often require case-sensitive matches.

        ## OKTA SDK USAGE RULES (Specific to `client` object) ##
        1.  Use `client.SomeOktaMethod(...)` for Okta SDK calls (i.e., assume an Okta client object named `client`).
        2.  **For direct SDK methods (those listed in `{sdk_methods}` that are not utilities):**
            *   Always use the tuple unpacking pattern: `result_object, http_response, error = await client.SomeOktaMethod(...)`
            *   Check for errors immediately: `if error: return {{"status": "error", "error": str(error)}}`
        3.  **IMPORTANT EXCEPTION for Utility Functions (e.g., `paginate_results` from `{utility_methods}`):**
            *   Do NOT use tuple unpacking. Instead, assign the direct result: `users_list = await paginate_results(client.list_users, query_params={{...}})`
            *   Error checking for utility functions: `if isinstance(users_list, dict) and 'status' in users_list and users_list['status'] == 'error': return users_list`
        4.  Use the `.as_dict()` method to convert Okta model objects to Python dictionaries (e.g., `user_dict = user_object.as_dict()`). Do NOT use `to_dict()`.

        ## ERROR HANDLING REQUIREMENTS ##
        *   **General Principle:** Each step must handle potential errors gracefully.
        *   **For Single Entity Operations (e.g., get_user, get_group):**
            *   If the entity is not found (and the SDK indicates this, often via a specific error type or a 404 response check if applicable): `return {{"status": "not_found", "entity_type": "user", "identifier": entity_id_or_name}}` (adjust `entity_type` and `identifier` as appropriate).
            *   If a general error occurs during the operation: `return {{"status": "error", "error": str(err)}}` (where `err` is from the SDK call or a caught exception).
            *   If successful: Return the processed data directly (e.g., a dictionary for a single user, a specific requested attribute).
        *   **For Multiple Entity Operations (e.g., list_users, search_groups):**
            *   If no entities are found matching the criteria: Return an empty list `[]` or empty dictionary `{{}}` as appropriate for the expected data structure.
            *   If an error occurs during the main listing/searching operation: `return {{"status": "error", "error": str(err)}}`.
        *   **For "Foreach" Operations on Multiple Entities (e.g., iterating through a list of users to update them):**
            *   Continue processing other entities even if one or more individual operations fail.
            *   Track the status of each individual operation. The final result should be a list of status objects, e.g.:
                `results = []`
                `for item in item_list:`
                `  # ... attempt operation ...`
                `  if success: results.append({{"id": item_id, "status": "success", "data": {{...}}}})`
                `  else: results.append({{"id": item_id, "status": "failed", "error": "reason"}})`
                `return results`
        *   **For Dependent Operations (where a step relies on the output of a previous step):**
            *   Before proceeding, check if the result from the prerequisite step indicates an error or is unexpectedly empty.
            *   If prerequisite failed or returned unusable data: `return {{"status": "dependency_failed", "dependency_step_name": "name_or_description_of_previous_step", "reason": "Details of why it failed, e.g., 'Previous step returned an error: <error_message>' or 'Required data not found in previous step output.'" }}`.

        ## DATA EXTRACTION & SERIALIZATION ##
        1.  **Specificity is Key:** Always extract ONLY the specific data fields or attributes mentioned in the step description.
            *   If a step asks for "email addresses of users," return a simple list of email strings: `["user1@example.com", "user2@example.com"]`.
            *   If a step asks for "names and departments of groups," return a list of dictionaries, each containing only 'name' and 'department' keys: `[ {{"name": "Group A", "department": "IT"}}, {{...}} ]`.
        2.  **No Extra Fields:** Never include additional fields or the full object structure beyond what was specifically requested in the step.
        3.  **Careful Parsing:** Parse the step description carefully to determine exactly what data to extract and in what format (simple list of values, list of objects with specific keys, etc.).
        4.  **JSON Serializable Data Structures:**
            *   NEVER use Python `set` literals (`{{'a', 'b'}}`) or set comprehensions, as they are not directly JSON serializable.
            *   Always use `list` for collections. For unique items, build a list and check for existence before appending:
                `unique_ids = []`
                `if new_id not in unique_ids: unique_ids.append(new_id)`
            *   For creating a unique lookup or ensuring uniqueness before adding to a list, a dictionary can be used as a temporary helper: `id_lookup = {{user["id"]: True for user in users}}` then `if some_id in id_lookup: ...`
            *   All returned data structures must be JSON serializable (composed of `dict`, `list`, `str`, `int`, `float`, `bool`, `None`).

        ## ENTITY SEARCH/LISTING RULES ##
        1.  If the user query or step description does not explicitly state "match exactly" or use precise filter language, default to a "contains" (co) or "starts with" (sw) search where appropriate for the Okta SDK method being used (e.g., in `search` or `q` parameters).

        ## RESPONSE FORMAT (Code Block Structure) ##
        You must format your response containing the generated code as follows, with each step in its own block:

        <STEP-1>
        users_result, _, err = await client.list_users(query_params={{"search": "profile.firstName eq \\"John\\""}})
        if err:
            return {{"status": "error", "error": str(err)}}

        if not users_result:
            return []

        extracted_data = [user.as_dict()["profile"]["email"] for user in users_result if user.as_dict().get("profile", {{}}).get("email")]
        return extracted_data
        </STEP-1>

        <STEP-2>
        if isinstance(extracted_data, dict) and "status" in extracted_data:
            return {{"status": "dependency_failed", "dependency_step_name": "Step 1 - Fetch Users", "reason": f"Previous step error: {{extracted_data.get('error', 'Unknown error')}}"}}
        if not extracted_data:
            return []

        processed_step_2_data = [email.upper() for email in extracted_data]
        return processed_step_2_data
        </STEP-2>
        ... and so on for all steps.

        ---
        Please generate all {len(plan.steps)} steps now, with clear Python code for each step, following all the rules meticulously.
        Remember: **NO COMMENTS OR DOCSTRINGS IN THE ACTUAL GENERATED PYTHON CODE.** (The Python code examples within this prompt are for *your* understanding of the required output format, not for you to reproduce comments from them).
        The python code within the `<STEP-N>...</STEP-N>` blocks should be raw code.
        """
        
    def _extract_step_codes(self, response: str, expected_steps: int) -> List[str]:
        """Extract code blocks for each step from the response."""
        code_blocks = []
        
        # Try to extract using <STEP-X> tags first
        for i in range(1, expected_steps + 1):
            pattern = rf'<STEP-{i}>(.*?)</STEP-{i}>'
            match = re.search(pattern, response, re.DOTALL)
            
            if match:
                code_blocks.append(match.group(1).strip())
            else:
                # Try alternative extraction methods
                # Look for markdown code blocks with step indicators
                block_pattern = rf'(?:Step|STEP) {i}[:\s].*?```(?:python)?\s*(.*?)```'
                block_match = re.search(block_pattern, response, re.DOTALL)
                
                if block_match:
                    code_blocks.append(block_match.group(1).strip())
                else:
                    # Last resort - look for numbered sections
                    section_pattern = rf'(?:^|\n)(?:#{1,6}|)\s*(?:Step|STEP) {i}[:\s].*?(?:\n)(.*?)(?:\n\s*(?:#{1,6}|)(?:Step|STEP) {i+1}|$)'
                    section_match = re.search(section_pattern, response, re.DOTALL)
                    
                    if section_match:
                        # Clean the content to extract just the code
                        content = section_match.group(1).strip()
                        # Remove any markdown code block markers
                        content = re.sub(r'```python|```', '', content)
                        code_blocks.append(content.strip())
                    else:
                        # If all extraction methods fail, use placeholder
                        code_blocks.append(f"# Missing code for step {i}\nraise ValueError('Code generation failed for step {i}')")
        
        # If we have fewer blocks than expected, add placeholders
        while len(code_blocks) < expected_steps:
            i = len(code_blocks) + 1
            code_blocks.append(f"# Missing code for step {i}\nraise ValueError('Code generation incomplete for step {i}')")
            
        return code_blocks

# Create a singleton instance
coding_agent = CodingAgent()

# For interactive testing
if __name__ == "__main__":
    import asyncio
    from src.core.realtime.agents.reasoning_agent import ExecutionPlan, PlanStep
    
    async def test():
        # Create a simple test plan
        plan = ExecutionPlan(
            steps=[
                PlanStep(
                    tool_name="search_users",
                    query_context="Find users with firstName Noah",
                    critical=True,
                    reason="To find users with the specified name"
                ),
                PlanStep(
                    tool_name="get_user_details",
                    query_context="Get email address of users found in step 1",
                    critical=True,
                    reason="To extract email addresses"
                )
            ],
            reasoning="Find email address of user named Noah"
        )
        
        # Test with tool registry (no docs needed)
        try:
            # Use a test flow ID
            result = await coding_agent.generate_workflow_code(plan, flow_id="test-flow")
            print("Generated code blocks using tool registry:")
            for i, code in enumerate(result.step_codes):
                print(f"\n--- STEP {i+1} ---")
                print(code)
        except Exception as e:
            print(f"Error with tool registry: {e}")
            
        # Test with explicit docs (original behavior)
        try:
            tool_docs = [
                "search_users: Search for users based on profile attributes",
                "get_user_details: Get detailed user information by ID"
            ]
            result = await coding_agent.generate_workflow_code(plan, tool_docs, flow_id="test-flow")
            print("\nGenerated code blocks with explicit docs:")
            for i, code in enumerate(result.step_codes):
                print(f"\n--- STEP {i+1} ---")
                print(code)
        except Exception as e:
            print(f"Error with explicit docs: {e}")
    
    # Uncomment to test
    # asyncio.run(test())