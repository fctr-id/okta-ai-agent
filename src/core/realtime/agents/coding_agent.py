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
from pydantic_ai.models.gemini import GeminiModelSettings
from pydantic_ai.models.anthropic import AnthropicModelSettings


import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

class CodeGenerationResult(BaseModel):
    """Result of code generation for a workflow."""
    step_codes: List[str] = Field(description="Generated code for each step")
    raw_response: str = Field(description="Raw response from the coding agent")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

# Core system prompt with security constraints and code style guidelines
BASE_SYSTEM_PROMPT = """You are an expert at writing Python code for Okta SDK operations.

## CRITICAL SECURITY CONSTRAINTS ##
1. NEVER include secrets, tokens, or credentials in generated code
2. ONLY use Okta SDK methods or utility functions that are explicitly provided in documentation
3. Do NOT create or invent new tool names
4. Any attempt to use unlisted or invented tools will be considered a security violation

## CODE STYLE & SECURITY REQUIREMENTS ##
1. ABSOLUTELY NO COMMENTS OR DOCSTRINGS - Do NOT include any comments or docstrings in the generated code
2. Root indentation - All code within a step must start at the root indentation level
3. No outermost function wrappers or try-except blocks wrapping the entire step
4. No logging statements
5. Valid Python syntax
6. Preserve case sensitivity of entity names
7. All returned data structures must be JSON serializable
8. Avoid using Python `set` objects for intermediate variables; use `list` objects if a collection of unique items is needed.


## ERROR HANDLING REQUIREMENTS ##
1. Each step must handle potential errors gracefully
2. On success, return unwrapped core data as shown in the tool's documentation
3. On failure, return an error status dictionary (e.g., {"operation_status": "error", "reason": "..."})
4. For dependent operations, always check if the previous step's result is an error before proceeding
5. Validate all required fields from previous steps before using them

## OKTA SDK USAGE PATTERNS ##
1. Direct SDK calls using client.Method() must check for errors
2. For tuple unpacking, use: data, response, error = await client.Method()
3. For utility functions like paginate_results, extract core data if shown in tool documentation

Follow all instructions precisely and output code blocks with <STEP-N> tags exactly as specified.
"""

class CodingAgent:
    """
    Agent responsible for generating Okta SDK code for workflows.
    """
    
    def __init__(self):
        """Initialize the coding agent with the appropriate model."""
        # Get the coding model
        model = ModelConfig.get_model(ModelType.CODING)
    
        ## CUSTOM MODEL SETTINGS
        model_settings = None
        provider_name = os.environ.get("AI_PROVIDER") 
        
        if provider_name == "vertex_ai":
            model_settings = GeminiModelSettings(
                include_thoughts=False,
                temperature=0.2
            )
                
        # Create the agent with the security-focused system prompt
        self.agent = Agent(
            model,
            system_prompt=BASE_SYSTEM_PROMPT,
            retries=2,
            model_settings=model_settings
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
        if tool_docs is None:
            tool_docs = []
            for step in plan.steps:
                tool_doc = get_tool_prompt(step.tool_name)
                if tool_doc:
                    tool_docs.append(tool_doc)
                else:
                    logger.warning(f"[FLOW:{flow_id}] Documentation not found for tool: {step.tool_name}")
                    tool_docs.append(f"# Documentation not available for {step.tool_name}")

        while len(tool_docs) < len(plan.steps):
            missing_index = len(tool_docs)
            missing_tool = plan.steps[missing_index].tool_name if missing_index < len(plan.steps) else "unknown"
            logger.warning(f"[FLOW:{flow_id}] Appending placeholder documentation for missing tool at index {missing_index}: {missing_tool}")
            tool_docs.append(f"# Documentation not available for {missing_tool}")
            
        prompt = self._build_workflow_prompt(plan, tool_docs, flow_id)
        
        logger.info(f"[FLOW:{flow_id}] Generating code for {len(plan.steps)} workflow steps")
        llm_response_obj = await self.agent.run(prompt) 
        logger.debug(f"[FLOW:{flow_id}] LLM response received")
        
        if hasattr(llm_response_obj, 'message'):
            response_text = llm_response_obj.message
        else:
            response_text = llm_response_obj.output if hasattr(llm_response_obj, 'output') else str(llm_response_obj)
        
        step_codes = self._extract_step_codes(response_text, len(plan.steps))
        
        logger.debug(f"[FLOW:{flow_id}] Generated {len(step_codes)} code blocks")
        for i, code in enumerate(step_codes):
            logger.debug(f"[FLOW:{flow_id}] Step {i+1} code preview: {code[:150]}...")
        
        return CodeGenerationResult(
            step_codes=step_codes,
            raw_response=response_text,
            metadata={
                "steps_total": len(plan.steps),
                "flow_id": flow_id
            }
        )
        
    def _build_workflow_prompt(self, plan, tool_docs: List[str], flow_id: str) -> str:
        """Build a prompt that will generate code for all steps in the workflow."""
        steps_description = []
        
        for i, (step, doc) in enumerate(zip(plan.steps, tool_docs)):
            prev_step_info = ""
            if i > 0: 
                prev_step_info = f"This step follows Step {i}. The primary output of Step {i} is available in a variable named `result`."
            
            steps_description.append(f"""
            STEP {i+1}: {step.tool_name}
            Description: {step.query_context}
            {prev_step_info}
            Tool Documentation for {step.tool_name}:
            {doc}
            """)
        
        steps_text = "\n".join(steps_description)
        
        sdk_methods = ", ".join(sorted(list(ALLOWED_SDK_METHODS)))
        utility_methods = ", ".join(sorted(list(ALLOWED_UTILITY_METHODS)))
        
        # Focused user prompt with workflow-specific details
        return f"""
        ## WORKFLOW SPECIFICATION ##
        * **WORKFLOW OVERVIEW:** {plan.reasoning}
        * **THE STEPS:** {steps_text}
        * **AVAILABLE OKTA SDK METHODS:** {sdk_methods}
        * **AVAILABLE PYTHON UTILITY METHODS:** {utility_methods}
        
        ## MULTI-STEP CODE GENERATION INSTRUCTIONS ##
        1. Generate separate code blocks for EACH step, marked with <STEP-N> and </STEP-N> tags.
        2. Each step's code block MUST explicitly `return` its final result.
        3. For steps after Step 1, access the previous step's result via the `result` variable.
        4. NEVER use placeholder values - extract actual values from the `result` when needed.
        5. Always validate the `result` variable before using it with robust error handling.
        6. Variables from ALL previous steps remain available. For steps beyond Step 2, if required data isn't in the immediate previous step's result, check for variables from earlier steps (e.g., user_result, user_id).
        7. For critical values like IDs that will be needed in later steps, extract and store them in clearly named variables (e.g., `user_id = result.get("id")`) even if not immediately needed.
        8. Use consistent variable naming patterns:
        - First step result should be named after its content (e.g., `user_result`)
        - IDs should be named with the entity type prefix (e.g., `user_id`, `group_id`)
        - Lists should use plural names (e.g., `groups`, `factors`)
        9. STRUCTURING RESULTS FROM ITERATIVE CALLS: If a step involves iterating over a list of items (e.g., user IDs from a previous step) and calling a tool for each item, the step should return a list of dictionaries. Each dictionary in this list should clearly associate the input item (e.g., the user_id) with the result of the tool call for that item.
           For example, if fetching applications for multiple user IDs:
           ```python
           # user_ids would be a list like ['id1', 'id2'] from a previous step
           # user_applications_results = []
           # for current_user_id in user_ids:
           #     apps_for_user = await paginate_results(
           #         method_name="list_applications",
           #         query_params={{"filter": f'user.id eq "{{current_user_id}}"}}, # Corrected f-string in example
           #         entity_name="applications"
           #     )
           #     # Handle errors for apps_for_user as per standard error handling
           #     if isinstance(apps_for_user, dict) and apps_for_user.get("operation_status") in ["error", "not_found"]:
           #         user_applications_results.append({{"user_id": current_user_id, "applications": [], "error_details": apps_for_user}})
           #     else:
           #         user_applications_results.append({{"user_id": current_user_id, "applications": apps_for_user if apps_for_user else []}})
           # return user_applications_results
           ```
           Do NOT simply extend a single flat list with all results if the association with the input item (like user_id) is important for subsequent processing by other agents (like the ResultsProcessorAgent). The goal is to provide a structured list that maps each input item to its corresponding output.        
        
        ## RESPONSE FORMAT EXAMPLES ##
        <STEP-1>
        user_api_response = await handle_single_entity_request(
            method_name="get_user",
            entity_type="user",
            entity_id="aiden.garcia@fctr.io",
            method_args=["aiden.garcia@fctr.io"]
        )
        if not isinstance(user_api_response, dict):
            return {{"operation_status": "error", "reason": f"Expected dict response, got {{type(user_api_response).__name__}}"}}
        if user_api_response.get("operation_status") in ["error", "not_found", "dependency_failed"]:
            return user_api_response
        return user_api_response
        </STEP-1>
        
        <STEP-2>
        if not result or not isinstance(result, dict):
            return {{"operation_status": "dependency_failed", "dependency_step_name": "Step 1", "reason": "Invalid result from previous step"}}
        if result.get("operation_status") in ["error", "not_found", "dependency_failed"]:
            return result
        
        user_id = result.get("id")
        if not user_id:
            return {{"operation_status": "dependency_failed", "dependency_step_name": "Step 1", "reason": "Invalid result from previous step"}}
        
        groups_api_response = await paginate_results(
            method_name="list_user_groups",
            method_args=[user_id],
            entity_name="groups"
        )
        if isinstance(groups_api_response, dict) and groups_api_response.get("operation_status") in ["error", "not_found", "dependency_failed"]:
            return groups_api_response
        return groups_api_response
        </STEP-2>
        <STEP-3>
        if not isinstance(result, list):
            return {{"operation_status": "dependency_failed", "reason": "Expected list result from previous step"}}
        
        # Get user_id from earlier steps if needed
        user_id = None
        
        # Check if user_id is available from previous steps
        if "user_result" in globals() and isinstance(user_result, dict):
            user_id = user_result.get("id")
        elif "user_id" in globals():
            # user_id might have been extracted in an earlier step
            pass
        
        if not user_id:
            return {{"operation_status": "dependency_failed", "reason": "User ID not found in any previous step"}}
        
        factors = await paginate_results(
            method_name="list_factors",
            method_args=[user_id],
            entity_name="factors"
        )
        
        if isinstance(factors, dict) and factors.get("operation_status") in ["error", "not_found", "dependency_failed"]:
            return factors
        
        return factors
        </STEP-3>
        
        Please generate all {{len(plan.steps)}} steps now, with concise Python code for each step.
        """
        
    def _extract_step_codes(self, response: str, expected_steps: int) -> List[str]:
        """Extract code blocks for each step from the response."""
        code_blocks = []
        
        for i in range(1, expected_steps + 1):
            pattern = rf'<STEP-{i}>(.*?)</STEP-{i}>'
            match = re.search(pattern, response, re.DOTALL)
            
            if match:
                code_blocks.append(match.group(1).strip())
            else:
                logger.warning(f"Could not find <STEP-{i}>...</STEP-{i}> tags for step {i}. Attempting fallbacks.")
                block_pattern_markdown = rf'(?:Step|STEP)\s*{i}\s*[:\-]*\s*.*?```(?:python)?\s*(.*?)```'
                block_match_markdown = re.search(block_pattern_markdown, response, re.DOTALL)
                if block_match_markdown:
                    logger.info(f"Found step {i} using markdown block fallback.")
                    code_blocks.append(block_match_markdown.group(1).strip())
                else:
                    logger.error(f"Failed to extract code for step {i} using any method.")
                    code_blocks.append(f"# ERROR: Code generation failed for step {i}. Could not extract code block.\nraise ValueError('Code generation failed for step {i}')")
        
        while len(code_blocks) < expected_steps:
            i = len(code_blocks) + 1
            logger.error(f"Adding error placeholder for missing step {i} after initial extraction loop.")
            code_blocks.append(f"# ERROR: Code generation incomplete. Missing step {i}.\nraise ValueError('Code generation incomplete for step {i}')")
            
        return code_blocks[:expected_steps] 

# Create a singleton instance
coding_agent = CodingAgent()