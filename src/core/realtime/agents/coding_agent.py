from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import re
import logging
from pydantic_ai import Agent
from src.core.model_picker import ModelConfig, ModelType
from src.core.realtime.code_execution_utils import ALLOWED_SDK_METHODS, ALLOWED_UTILITY_METHODS


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
            # No result_type as we'll parse the output manually
        )
        
    async def generate_workflow_code(self, plan, tool_docs: List[str], flow_id: str = "unknown") -> CodeGenerationResult:
        """
        Generate code for all steps in a workflow.
        
        Args:
            plan: The execution plan with steps
            tool_docs: Documentation for each tool in the plan
            flow_id: Unique identifier for the current flow/conversation
            
        Returns:
            CodeGenerationResult with code for each step
        """
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
        You are an expert at writing Python code for Okta SDK operations with robust error handling.
        
        I need you to write code for a multi-step workflow that interacts with Okta.
        
        WORKFLOW OVERVIEW:
        {plan.reasoning}
        
        THE STEPS:
        {steps_text}
        
        IMPORTANT INSTRUCTIONS:
        NOTE: To any of the code generated for steps do not use comments or docstrings.
        1. Generate separate code blocks for EACH step
        2. Each code block should be marked with <STEP-1>, <STEP-2>, etc.
        3. Each step should explicitly RETURN its final result
        4. Later steps can use variables from earlier steps directly
        5. Use proper error handling for each step
        
        CODE FORMAT REQUIREMENTS:
        - Make sure code is at the root indentation level (no initial indents)
        - Do not include function definitions or try-except blocks at the outermost level
        - Do not use logging functions directly (logging.info, logging.error, etc.)
        - Ensure all code is valid Python syntax that can be executed directly
        
        ENTITY RULES:
         1. If the user doesn't specify to match exactly, use co or starts with when listing or searching for entities
        
        ERROR HANDLING REQUIREMENTS:
        - For single entity operations:
          - If entity not found: return {{"status": "not_found", "entity": "user|group|etc", "id": entity_id}}
          - If error occurs: return {{"status": "error", "error": str(err)}}
          - If successful: return processed data with no special wrapper
        
        - For multiple entity operations (like lists or searches):
          - If no entities found: return empty list/dict (not an error)
          - If error occurs: return {{"status": "error", "error": str(err)}}
          - For foreach operations on multiple entities, continue processing even if some fail
          - Track failures for individual entities: [{{"id": "123", "status": "success", "data": {{...}}}}]
        
        - For dependent operations (e.g., get user groups):
          - If prerequisite failed: return {{"status": "dependency_failed", "dependency": "step_name", "error": "Reason"}}
          - Handle both empty and error cases appropriately
        
        ALLOWED OKTA SDK METHODS:
        {sdk_methods}
        
        ALLOWED UTILITY METHODS:
        {utility_methods}
        
        TECHNICAL REQUIREMENTS:
        6. Use client.X for Okta SDK calls (not okta_client)
        7. Always use the tuple unpacking pattern: object, resp, err = await client.X
        8. Always check for errors with: if err: return {{"status": "error", "error": str(err)}}
        9. Use as_dict() (not to_dict()) to convert Okta objects to dictionaries
        10. For list operations, use: [item.as_dict() for item in items]
        11. For collecting results, use list comprehensions instead of append: emails = [user["profile"]["email"] for user in users_list]
        
        CRITICAL DATA EXTRACTION REQUIREMENTS:
        - Always extract ONLY the specific data mentioned in the step description
        - If the step says "extract email addresses", return a simple list of email strings
        - If the step says "get names and departments", return a list of objects with only those fields
        - Never include additional fields beyond what was specifically requested
        - Parse the step description carefully to determine exactly what data to extract
        - For simple field extraction (email/name/etc), return a simple list of values, not objects with IDs and status
        
        FORMAT YOUR RESPONSE LIKE THIS:
        
        <STEP-1>
        users, resp, err = await client.list_users(query_params={{"search": "profile.firstName eq \\"John\\""}})
        if err:
            return {{"status": "error", "error": str(err)}}
            
        users_list = [user.as_dict() for user in users]
        if not users_list:
            return []
            
        return users_list
        </STEP-1>
        
        <STEP-2>
        if isinstance(users_list, dict) and "status" in users_list and users_list["status"] == "error":
            return {{"status": "dependency_failed", "dependency": "search_users", "error": users_list["error"]}}
        
        if not users_list:
            return []
            
        # Extract only email addresses as mentioned in the step description
        emails = []
        for user in users_list:
            try:
                email = user["profile"]["email"]
                if email:
                    emails.append(email)
            except KeyError:
                continue
                
        # Return just the list of emails, not full objects with IDs
        return emails
        </STEP-2>
        
        Please generate all {len(plan.steps)} steps now, with clear code for each step.
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
        
        # Sample tool docs for test
        tool_docs = [
            "search_users: Search for users based on profile attributes",
            "get_user_details: Get detailed user information by ID"
        ]
        
        try:
            # Use a test flow ID
            result = await coding_agent.generate_workflow_code(plan, tool_docs, flow_id="test-flow")
            print("Generated code blocks:")
            for i, code in enumerate(result.step_codes):
                print(f"\n--- STEP {i+1} ---")
                print(code)
        except Exception as e:
            print(f"Error: {e}")
    
    # Uncomment to test
    # asyncio.run(test())