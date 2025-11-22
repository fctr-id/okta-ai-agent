"""
Results Processor Agent for Okta AI Agent.

This module is responsible for processing raw execution results into user-friendly formats:
- Determines appropriate output type based on query and data
- Generates formatting/processing code for large datasets
- Creates direct formatted output for smaller datasets
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from pydantic_ai import Agent
from src.core.models.model_picker import ModelConfig, ModelType
from src.utils.logging import get_logger
from src.utils.security_config import ALLOWED_SDK_METHODS, ALLOWED_UTILITY_METHODS
from src.core.models.model_picker import ModelConfig, ModelType
import json
import re
import textwrap

logger = get_logger(__name__)

class ProcessingResponse(BaseModel):
    """Output structure for the Results Processor."""
    display_type: str = Field(description="Type of display format (markdown, table)")
    content: Any = Field(description="Formatted content for display")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional display metadata")
    processing_code: Optional[str] = Field(default=None, description="Python code for processing large datasets")

class ResultsProcessorAgent:
    """Agent for processing execution results into user-friendly formats."""
    
    def __init__(self, model_config: Optional[ModelConfig] = None):
        """Initialize the Results Processor Agent."""
        
        # System prompt that guides the agent's behavior
        system_prompt = """
        You are an expert at processing and formatting Okta data for clear presentation to users.
        
        Your job is to:
        1. Analyze query results from Okta API calls
        2. Format the results to directly answer the user's original query
        3. Choose the most appropriate display format (markdown or table)
        4. For large datasets, generate Python code to process the full dataset
        
        IMPORTANT: Markdown is only useful when you need to provide a summary or explanation which cannot be more than 10 lines. Otherwise , you can just pass the data as provided to you in the table format.
        
        ### Key Okta Entities and Their Relationships ###
        
        * **User (Identity):**
          * Has unique ID, email, login
          * Can belong to Groups (many-to-many)
          * Can be assigned to Applications (many-to-many)
          * Can have multiple Factors (one-to-many)
          * Status must be ACTIVE for most operations
        
        * **Group:**
          * Collection of Users (many-to-many)
          * Has unique ID and name
          * Can be assigned to Applications (many-to-many)
        
        * **Application (App):**
          * Has unique ID, label, and status
          * Users access via direct assignment or Group membership
          * Linked to one Authentication Policy
        
        * **Factor:**
          * Associated with one User
          * Represents an MFA method (SMS, Email, Push, etc.)
          * Has unique ID, type, provider, status
        
        * **Policy and Rules:**
          * Apps link to Policies which contain ordered Rules
          * Rules have conditions and actions (ALLOW/DENY)
          * Rules reference Groups and Network Zones
        
        * **Network Zone:**
          * Defines IP/location conditions used in Policy Rules
          * Has unique ID, name, and type        
        
        IMPORTANT OUTPUT FORMAT INSTRUCTIONS:
        - Return ONLY a valid JSON object in one of the two formats shown below
        - Choose ONLY ONE format type (markdown OR table) - do NOT use combined type
        - When using markdown, use <br> for line breaks in the content
        - Do NOT include markdown code blocks around your JSON output
        - The response must contain ONLY the JSON object, nothing else
        - DO NOT remove any results from the data set provided to you when creating the code for large datasets
        - you MUST Process and return ALL items from the dataset, regardless of size
        
        EXAMPLE 1 - MARKDOWN FORMAT:
        {
          "display_type": "markdown", 
          "content": "# User Information for johndoe@example.com\n\n## Profile\n- Full Name: John Doe\n- Email: johndoe@example.com\n- Status: ACTIVE\n\n## Group Memberships\n- Marketing Team\n- Sales Department\n- All Users",
          "metadata": {{}}
        }
        
        EXAMPLE 2 - TABLE FORMAT (VUE-COMPATIBLE):
        {
        "display_type": "table",
        "content": [
            {
            "name": "John Doe",
            "email": "johndoe@example.com",
            "status": "ACTIVE",
            "groups": "Marketing, Sales, All Users"
            },
            {
            "name": "Jane Smith",
            "email": "jsmith@example.com",
            "status": "ACTIVE",
            "groups": "Engineering, All Users"
            }
        ],
        "metadata": {
            "headers": [
            {
                "align": "start",
                "value": "name",
                "sortable": true,
                "text": "User Name"
            },
            {
                "value": "email",
                "sortable": true,
                "text": "Email Address"
            },
            {
                "value": "status",
                "sortable": true,
                "text": "Account Status"
            },
            {
                "value": "groups",
                "sortable": false,
                "text": "Group Memberships"
            }
            ]
         }
        }
        
        For TABLE FORMAT, the structure should be as shown in "EXAMPLE 2 - TABLE FORMAT (VUE-COMPATIBLE)" above:
        - "display_type" is "table".
        - "content" MUST be an array of the data item objects (the rows).
        - "metadata" MUST be an object.
        - "metadata.headers" MUST be an array of header definition objects.
        - Each header object in "metadata.headers" MUST use "text" for the display title and "value" for the data key (which corresponds to a key in the item objects). It MAY also include "align" and "sortable".
        
        WHEN TO USE MARKDOWN:
        - When you have the "FULL" dataset and the user's original query is something you can answer with a summary in markdown and less than 5 items 
        - you can MUST use markdown tables when you have a small dataset (5 or fewer items) and the data is not too verbose
        - Make sure you read the users question carefully and understand what their intent is and then answer it thoroughly 
        - Results that require explanatory text or descriptions
        - When presenting facts or data that are not easily tabularized
        - you must use <br> for line breaks in markdown content NOT \n or \r\n
        - When using markdown to provide a summary or explanation of the data, make sure to include all relevant details in the markdown content. The more details you provide, the better the user will understand the results.
        - If the answer to the user's query is NOT a definite YES or NO, but depdends on certain contritions like acls, policy, factors ..etc, say 'It Depends' and explain your answer in the markdown content.
        
        WHEN TO USE TABLE:
        - For lists of similar items (users, groups, applications)
        - When data has consistent fields across items
        - When you have a "SAMPLE" of a large dataset and need to generate Python code to process the full dataset
        - Consistent data with the same fields for each record
        
        ## Critical Results Requirements
                - For tables: 
                    - Include all items (rows) in the "content" array (which should be the top-level "content" field, not nested).
                    - As per guideline 3, `metadata.headers` may be a selection of fields for readability if objects are verbose, but each object in the `content` (items) array must be the complete, original data for that item.
                    - Return a dict with keys: `display_type`, `content`, and `metadata`.
                    -  For tables, as per "EXAMPLE 2 - TABLE FORMAT (VUE-COMPATIBLE)":
                    - The top-level `content` field MUST be an array of the data item objects.
                    - The `metadata` field MUST be an object containing a `headers` array.
                    - `metadata.headers`: An array of column definition objects. Each object MUST have `value` (string, corresponding to a property in the item objects) and `text` (string, for display). It MAY also have `align` (e.g., "start", "center", "end") and `sortable` (boolean).
                    - `content` (items array): An array of the **complete data objects** as received or processed. The properties referenced by `header.value` (from `metadata.headers`) must exist in these objects.
        
        Always prioritize clarity and directness in answering the user's query.
        """
        
        # Get the REASONING model since that's more appropriate for data formatting
        model = model_config or ModelConfig.get_model(ModelType.REASONING)
        
        # Create the agent with the model and system prompt
        self.agent = Agent(
            model=model,
            system_prompt=system_prompt
        )
    
    async def process_results(self, query: str, results: dict, original_plan: Any, 
                             is_sample: bool = False, metadata: dict = None) -> ProcessingResponse:
        """Process execution results into a user-friendly format."""
        
        if not metadata:
            metadata = {}
        
        flow_id = metadata.get("flow_id", "unknown")
        logger.info(f"[{flow_id}] Processing results for query: {query}")
        
        try:
            # Create the appropriate prompt based on whether we're dealing with sample data
            if is_sample:
                user_prompt = self._create_sample_data_prompt(query, results, original_plan)
            else:
                user_prompt = self._create_complete_data_prompt(query, results, original_plan)
            
            # Call the processor agent
            response = await self.agent.run(user_prompt)
            
            # Log the raw response for debugging
            logger.debug(f"[{flow_id}] Raw agent response: {response.output}")
            
            # Parse the response into a ProcessingResponse object
            processing_response = self._parse_response(response.output, is_sample, flow_id)
            return processing_response
            
        except Exception as e:
            logger.error(f"[{flow_id}] Error processing results: {str(e)}")
            # Return a basic error response
            return ProcessingResponse(
                display_type="markdown",
                content=f"**Error processing results**: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _parse_response(self, response: str, is_sample: bool, flow_id: str) -> ProcessingResponse:
        """Parse the agent's response into a ProcessingResponse object."""
        # First, log the raw response for debugging
        logger.debug(f"[{flow_id}] Parsing response: {response}")
        
        if is_sample:
            # Extract code from between <CODE> and </CODE> tags - case insensitive
            code_pattern = r'<CODE>(.*?)</CODE>'
            match = re.search(code_pattern, response, re.DOTALL | re.IGNORECASE)
            
            if match:
                # Extract the code
                raw_code = match.group(1).strip()
                
                # Remove any import statements
                import_pattern = r'^import\s+[a-zA-Z0-9_.]+.*$'
                cleaned_lines = []
                
                for line in raw_code.splitlines():
                    if not re.match(import_pattern, line.strip()):
                        cleaned_lines.append(line)
                    else:
                        # Comment out the import
                        cleaned_lines.append(f"# {line} - handled by execution environment")
                
                code = '\n'.join(cleaned_lines)
                
                logger.debug(f"[{flow_id}] Extracted processing code: {len(code)} chars")
                
                return ProcessingResponse(
                    display_type="code_generated",
                    content="Code generated for large dataset processing",
                    processing_code=code,
                    metadata={"requires_processing": True}
                )
            else:
                # If no code found, return error response
                logger.warning(f"[{flow_id}] Failed to extract processing code")
                return ProcessingResponse(
                    display_type="markdown",
                    content="*Failed to generate processing code for large dataset*",
                    metadata={"error": "code_extraction_failed"}
                )
        else:
            # For regular data, we expect a JSON response, but it might be wrapped in markdown code blocks
            # First, try to extract JSON from markdown code blocks if present
            cleaned_response = self._extract_json_from_markdown(response, flow_id)
            
            try:
                # Try to parse the cleaned response as JSON
                data = json.loads(cleaned_response)
                
                # Validate the structure
                if "display_type" in data and "content" in data:
                    display_type = data["display_type"]
                    if display_type not in ["markdown", "table"]:
                        logger.warning(f"[{flow_id}] Invalid display type: {display_type}, defaulting to markdown")
                        display_type = "markdown"
                    
                    return ProcessingResponse(
                        display_type=display_type,
                        content=data["content"],
                        metadata=data.get("metadata", {})
                    )
                else:
                    logger.warning(f"[{flow_id}] Missing required fields in JSON response")
                    raise ValueError("Invalid response format: missing required fields")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[{flow_id}] Error parsing JSON response: {str(e)}")
                
                # Fallback: Try to extract any object-like structure from the response
                fallback_result = self._extract_fallback_response(response, flow_id)
                if fallback_result:
                    return fallback_result
                
                # Return error response if all extraction attempts fail
                return ProcessingResponse(
                    display_type="markdown", 
                    content="*Error processing results: Invalid response format*",
                    metadata={"error": "invalid_format"}
                )
    
    def _extract_json_from_markdown(self, response: str, flow_id: str) -> str:
        """
        Extract JSON from a markdown-formatted response.
        
        Args:
            response: The raw response text
            flow_id: The flow ID for logging
            
        Returns:
            Cleaned JSON string ready for parsing
        """
        # Try several patterns to extract JSON
        
        # Pattern 1: Triple backticks with json language marker
        # ```json
        # {json content}
        # ```
        json_code_block = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', response, re.DOTALL)
        if json_code_block:
            extracted = json_code_block.group(1).strip()
            logger.debug(f"[{flow_id}] Extracted JSON from markdown code block: {len(extracted)} chars")
            return extracted
        
        # Pattern 2: Look for starting and ending braces that might contain JSON object
        # Useful for cases where the formatting is inconsistent
        json_object_pattern = re.search(r'(\{.*\})', response, re.DOTALL)
        if json_object_pattern:
            extracted = json_object_pattern.group(1).strip()
            logger.debug(f"[{flow_id}] Extracted potential JSON object: {len(extracted)} chars")
            return extracted
        
        # If no patterns match, return the original response for direct parsing attempt
        return response.strip()
    
    def _extract_fallback_response(self, response: str, flow_id: str) -> Optional[ProcessingResponse]:
        """
        Attempt to extract a usable response when JSON parsing fails.
        
        Args:
            response: The raw response text
            flow_id: The flow ID for logging
            
        Returns:
            ProcessingResponse if extraction successful, None otherwise
        """
        # Try to extract a table if the response contains table-like formatting
        if '|' in response and '-|-' in response:
            logger.info(f"[{flow_id}] Attempting to extract markdown table")
            return ProcessingResponse(
                display_type="markdown",
                content=response,  # Return the raw markdown
                metadata={"fallback": "markdown_table"}
            )
        
        # Look for structured content with headers/sections
        headers = re.findall(r'#+\s+(.+)$', response, re.MULTILINE)
        if headers:
            logger.info(f"[{flow_id}] Response contains {len(headers)} headers, treating as markdown")
            return ProcessingResponse(
                display_type="markdown",
                content=response,  # Return as markdown
                metadata={"fallback": "structured_markdown"}
            )
        
        # No suitable fallback found
        return None
    
    def _create_complete_data_prompt(self, query: str, results: Dict[str, Any], plan: Any) -> str:
        """Create a prompt for processing complete data."""
        # Extract plan reasoning if available
        plan_reasoning = getattr(plan, 'reasoning', 'No reasoning provided')
        
        # Convert results to a string
        results_str = json.dumps(results, default=str)
        if len(results_str) > 10000:
            results_str = results_str[:10000] + "... [truncated]"
        
        return f"""
        # Role: Expert Data Formatter & Presenter
        
        You are an expert at processing raw execution results and transforming them into a clear, user-friendly JSON response. Your primary goal is to directly answer the user's query using the provided data.
        
        ## Provided Inputs:
        1.  **Original User Query:**
            ```
            {query}
            ```
        2.  **Execution Plan Reasoning (Context for data generation):**
            ```
            {plan_reasoning}
            ```
        3.  **Complete Execution Results (Raw data to be processed):**
            ```
            {results_str}
            ```
        
        ## Your Primary Task:
        Process the "Complete Execution Results" to directly answer the "Original User Query".
        You MUST return your response as a single, valid JSON object.
        
        ## JSON Output Structure:
        Your JSON response MUST contain the following top-level keys:
        1.  `display_type`: (String) Either `"markdown"` or `"table"`.
        2.  `content`: (Varies) The formatted data.
        3.  `metadata`: (Object) Additional information about the content.
        
        ## Step 1: Choose `display_type` ("markdown" or "table")
        
        Select the most readable and useful format based on the data's nature, volume, and the user's query.
        
        **A. General Preference - MARKDOWN for:**
            *   **Small Datasets & Summaries:**
                *   When displaying **5 or fewer items** (e.g., users, groups, log entries).
                *   For verbose items (e.g., detailed JSON objects like raw log events), present each item clearly within markdown (e.g., formatted code blocks or summarized key-value lists).
                *   Creating brief summaries with a few key points (typically less than 5 total).
            *   **Narratives & Non-Tabular Data:**
                *   Presenting hierarchical or deeply nested information not suited for a flat table (especially with few items).
                *   Answering "why" or "how" questions with a narrative explanation.
                *   Showing statistical summaries or aggregated insights.
        
        **B. General Preference - TABLE for:**
            *   **Larger Datasets of Entities:**
                *   When displaying **more than 5 items** that are lists of similar entities (e.g., users, applications, groups, log entries) where items share common attributes suitable for columns.
            *   **Structured Comparison Focus:**
                *   When data, even if few items, primarily benefits from direct, column-by-column comparison or clear columnar organization (e.g., product SKUs, prices, stock).
            *   **Explicit User Request:** If the user's query asks for a table or implies a need for columnar data (e.g., "list users with columns for email and status").
        
        **C. Specific Guidance for Lists of Entities (users, apps, groups, logs, etc.):**
            *   **<= 5 Entities:** Default to **MARKDOWN**. Present each entity's information clearly and fully.
            *   **> 5 Entities:** Default to **TABLE**.
        
        ## Step 2: Format `content` and `metadata` based on `display_type`
        
        **A. If `display_type` is "markdown":**
            *   `content`: (String) A single, well-formatted markdown string.
            *   `metadata`: (Object) Can be an empty object `{{}}` or contain relevant information like `totalItems`.
            *   If the answer is ambiguous, you may start your markdown `content` with 'It depends...' or similar, followed by an explanation.
            *   If the questions are access related, you MUST provide detailed summary or explanation for your answer. The more details you provide, the better the user will understand the results.
            *   You MUST answer the query with a a clear explanation if the question asks if a user can or can not access some application looking at all the policies, rules, factors and network zones.
        
        **B. If `display_type` is "table":**
            *   **Strictly Adhere to "EXAMPLE 2 - TABLE FORMAT (VUE-COMPATIBLE)" from the main system prompt.** This example details the precise structure for Vuetify data tables.
            *   `content`: (Array) An array of data item objects. Each object represents one row in the table.
            *   `metadata`: (Object) MUST contain:
                *   `headers`: (Array) An array of header definition objects. Each header object:
                    *   MUST include `text`: (String) The display title for the column header.
                    *   MUST include `value`: (String) The key in the row objects (from `content`) that this column displays.
                    *   MAY include `align`: (String, e.g., 'start', 'center', 'end').
                    *   MAY include `sortable`: (Boolean).
            *   **CRITICAL for Vuetify Table Cell Compatibility (Refer to System Prompt Example 2):**
                *   Table cells (values within the row objects in `content`) expect primitive values (strings, numbers, booleans).
                *   If a data field for an item is naturally an array or list (e.g., a user's multiple group memberships), you **MUST** convert this array/list into a single, human-readable string (e.g., `"Admin, Editor, Viewer"`) before including it as a value in the `content`'s row object. The `value` in the corresponding `metadata.header` object must then point to the key holding this processed string.
            *   **Column Selection for Verbose Objects (Guideline from "Specific Guidance for Lists of Entities"):**
                *   If table items are verbose objects (e.g., detailed logs), the `metadata.headers` array should define a selection of the most **common, important, and representative fields** for initial display.
                *   However, each object within the `content` array (each row item) MUST still contain the **complete, unmodified data object** for that item. The headers guide display, but full data remains.
        
        ## Universal Content Requirements (Apply to BOTH Markdown and Table):
        *   **NO ITEM TRUNCATION:**
            *   NEVER limit the number of items (rows) displayed.
            *   ALWAYS include ALL relevant items (rows) in your response.
            *   NEVER include notes like "showing only a subset" or "first few results."
            *   NEVER use phrases like "due to space" when referring to the number of items (rows).
        *   **Thoroughness:** Answer the user's query comprehensively using all available relevant information from the "Complete Execution Results".
        
        ## General `metadata` Requirements (Apply to BOTH Markdown and Table):
        *   Include `totalItems`: (Integer) The total number of primary records/items processed and included in the `content`.
        *   Optionally include `queryTime`: (Integer) Processing time in milliseconds, if available.
        
        ## Final Output Constraints (VERY IMPORTANT):
        *   Your entire response MUST be a single, valid JSON object.
        *   DO NOT wrap the JSON response in markdown code blocks (e.g., \`\`\`json ... \`\`\`).
        *   DO NOT add any introductory text, concluding remarks, or any characters outside the main JSON object.
        *   **JSON VALIDITY:** Pay extreme attention to ensure the generated JSON is perfectly valid. This includes:
            *   Correctly escaping special characters within strings (e.g., `\\`, `\"`, `\\n`).
            *   Ensuring all strings are properly quoted.
            *   Correctly structuring arrays and objects.
            *   No trailing commas.
        """
    
    def _create_sample_data_prompt(self, query: str, results: Dict[str, Any], plan: Any) -> str:
        """Create a prompt for processing sample data."""
        # Extract plan reasoning if available
        plan_reasoning = getattr(plan, 'reasoning', 'No reasoning provided')
        
        # Extract execution steps if available
        execution_steps = []
        if hasattr(plan, 'steps') and isinstance(plan.steps, list):
            for i, step in enumerate(plan.steps):
                step_desc = getattr(step, 'description', f'Step {i+1}')
                tool = getattr(step, 'tool', 'Unknown tool')
                execution_steps.append(f"Step {i+1}: {tool} - {step_desc}")
        
        # Format execution steps as text
        execution_steps_text = "\n".join(execution_steps) if execution_steps else "No execution steps provided"
        
        # Convert results to a string
        results_str = json.dumps(results, default=str)
        if len(results_str) > 5000:
            results_str = results_str[:5000] + "... [truncated]"
        
        # Import the allowed methods list from security_config
        from src.utils.security_config import ALLOWED_UTILITY_METHODS
        
        # Filter string methods from the allowed utilities
        string_methods = sorted([method for method in ALLOWED_UTILITY_METHODS 
                                if method in dir(str) and not method.startswith('_')])
        
        # Other commonly used built-in functions and methods that are safe
        safe_builtins = "len, isinstance, dict, list, set, tuple, str, int, float, bool, range, enumerate"
        
        return f"""
        # Results Processing Task - SAMPLE DATA
        
        ## Original User Query
        {query}
        
        ## Execution Plan created by the Reasoning Agent to answer the user's query which will give you the information on what logic was used to get these results
        {plan_reasoning}
        
        ## Execution Steps generated by to implement the execution plan to get to these results mentioned below
        ##{execution_steps_text}
        
        ## Sample of Execution Results
        {results_str}
        
        ## Your Task
        You are receiving only a SAMPLE of a large dataset. 
        Write Python code WITHOUT function definitions that would process the complete dataset.
        
        Your code will be executed with the FULL dataset (available as variable 'full_results') 
        to transform it into a user-friendly format.
        
        IMPORTANT: Place your code between <CODE> and </CODE> tags. There MUST be the start tag <CODE> and the end tag </CODE> in your response. if NOT, throw an error.
        
        ## Data Structure Guidelines
        - ALWAYS START BY DEBUGGING THE DATA STRUCTURE: Print the structure before processing
        - IMPORTANT: Results may be structured in two ways - direct objects OR lists containing objects
        - Step results are numbered - key "1" contains results from step 1, etc.
        - NEVER assume data format without first checking its type
        - NEVER hardcode entity names - always extract names from the data dynamically
        
        ## Security Restrictions
        - DO NOT USE 'import' statements - modules like json are already available
        - DO NOT define any functions - no 'def' statements allowed
        - DO NOT use eval(), exec() or similar unsafe functions
        
        CRITICAL INSTRUCTION: Your code MUST NOT limit the number of items in the result.
        - DO NOT use slice operations like items[:200]
        - DO NOT implement any maximum item count
        - Return ALL items in the dataset regardless of how many there are
        - Tables will handle pagination in the UI; you shouldn't filter the data
        
        ## Allowed Methods
        - Only use string methods from this list: {', '.join(string_methods)}
        - Common built-ins: {safe_builtins}
        - Dictionary methods: get, items, keys, values
        - List methods: append, extend, insert, remove, pop, sort
        
        CRITICAL REQUIREMENTS FOR CODE GENERATION FOR DATA PROCESSING:
        - NEVER use Python sets or set operations - they are not JSON serializable
        - Instead of 'set()', use empty list: ids = []
        - Instead of '.add()', use if/not in check: if id not in ids: ids.append(id)
        - Always ensure ALL data structures are JSON serializable (dict, list, str, int, float, bool, None)
        - Your result MUST include 'display_type' and proper structure for displaying results          
        
        Example:
        
        <CODE>
        # Improved inspection of full_results, showing one level deeper for collections
        print(f"DEBUG: Inspecting full_results structure:")
        if isinstance(full_results, dict):
            for step_key, step_data_val in full_results.items():
                data_type_name = type(step_data_val).__name__
                details = f"Type: {{data_type_name}}"

                if isinstance(step_data_val, list):
                    details += f", Item count: {{len(step_data_val)}}"
                    if len(step_data_val) > 0:
                        first_item = step_data_val[0]
                        first_item_type_name = type(first_item).__name__
                        details += f", First item type: {{first_item_type_name}}"
                        if isinstance(first_item, dict):
                            first_item_keys = list(first_item.keys()) if first_item else []
                            details += f", First item keys: {{str(first_item_keys)}}"
                        elif isinstance(first_item, list): # Example for list of lists
                            details += f", First item is a list (length: {{len(first_item)}})"
                            if len(first_item) > 0:
                                inner_first_item = first_item[0]
                                inner_first_item_type = type(inner_first_item).__name__
                                details += f", First inner item type: {{inner_first_item_type}}"
                                if isinstance(inner_first_item, dict):
                                    inner_first_item_keys = list(inner_first_item.keys()) if inner_first_item else []
                                    details += f", First inner item keys: {{str(inner_first_item_keys)}}"
                elif isinstance(step_data_val, dict):
                    dict_keys = list(step_data_val.keys()) if step_data_val else []
                    details += f", Keys: {{str(dict_keys)}}"
                print(f"DEBUG: Step '{{step_key}}' -> {{details}}")
        else:
            print(f"DEBUG: full_results is not a dict, it's a {{type(full_results).__name__}}")

        # --- Data Extraction and Preparation ---
        # Step 1: Get data for the first group (e.g., Group A details)
        group1_data_raw = full_results.get("1", {{}}) # Default to empty dict
        group1_details = group1_data_raw[0] if isinstance(group1_data_raw, list) and len(group1_data_raw) > 0 else group1_data_raw
        group1_name = group1_details.get("profile", {{}}).get("name", "Group A") if isinstance(group1_details, dict) else "Group A"

        # Step 2: Get data for the second group (e.g., Group B details)
        group2_data_raw = full_results.get("2", {{}}) # Default to empty dict
        group2_details = group2_data_raw[0] if isinstance(group2_data_raw, list) and len(group2_data_raw) > 0 else group2_data_raw
        group2_name = group2_details.get("profile", {{}}).get("name", "Group B") if isinstance(group2_details, dict) else "Group B"

        # Step 3: Get users from the first group.
        # Assume each user object is structured like:
        # {{'user_id':'u1', 'profile':{{...}}, 'status':'ACTIVE', 
        #  'complex_attributes':[{{'attr_name':'Firewall Access', 'attr_value':'Enabled'}}, {{'attr_name':'VPN Type', 'attr_value':'SSL'}}]}}
        users_group1_raw = full_results.get("3", [])
        if not isinstance(users_group1_raw, list): users_group1_raw = []

        # Step 4: Get user IDs from the second group (for filtering).
        # Assume these are simpler, e.g., [{{'id': 'u3'}}, {{'id': 'u4'}}]
        users_group2_raw = full_results.get("4", []) # This step in the example is for filtering users.
                                                 # The actual complex list processing is demonstrated using 'complex_attributes' from users_group1_raw.
        if not isinstance(users_group2_raw, list): users_group2_raw = []

        group2_user_ids_for_filtering = []
        for user_g2_data in users_group2_raw:
            if isinstance(user_g2_data, dict):
                user_g2_id = user_g2_data.get("id")
                if user_g2_id and user_g2_id not in group2_user_ids_for_filtering:
                    group2_user_ids_for_filtering.append(user_g2_id)

        # --- Data Processing and Transformation ---
        items = []
        # This map will store user_id -> list of extracted attribute names
        user_to_attribute_names_map = {{}}

        # First, process the user records that might contain nested attribute dictionaries.
        # This part simulates processing a structure like full_results["4"] from your actual query,
        # where each record has a user_id and a list of complex objects (e.g., applications).
        # In this example, we use 'users_group1_raw' and its 'complex_attributes' field to demonstrate this pattern.
        # If your actual data for this pattern comes from a different step (e.g., full_results["X"]),
        # the agent should adapt this logic to use full_results["X"].
        
        # Let's assume the data with the nested list is in a hypothetical step "data_with_nested_list"
        # For this example, we'll use users_group1_raw as if it were that step.
        # The agent should identify the correct step in the real `full_results` that matches this structure.
        data_source_for_nested_lists = users_group1_raw # In a real scenario, this might be full_results.get("4") or similar

        for user_record_with_attributes in data_source_for_nested_lists: 
            if not isinstance(user_record_with_attributes, dict):
                continue

            # Get the user ID from this record. The key for user ID should be flexible.
            record_user_id = user_record_with_attributes.get("user_id") # Primary key to look for
            if not record_user_id:
                 record_user_id = user_record_with_attributes.get("id") # Fallback key
            if not record_user_id:
                # Try to find a user ID even if it's nested, e.g., in an 'actor' field
                actor_info = user_record_with_attributes.get("actor")
                if isinstance(actor_info, dict):
                    record_user_id = actor_info.get("id")
            if not record_user_id:
                continue # Cannot process without a user identifier

            # Get the list of attribute dictionaries (e.g., 'applications' in your real data)
            # The key for this list should be flexible.
            attributes_list_of_dicts = user_record_with_attributes.get("complex_attributes") # Example key
            if not attributes_list_of_dicts: # Fallback to other common names for such lists
                attributes_list_of_dicts = user_record_with_attributes.get("applications")
            if not attributes_list_of_dicts:
                attributes_list_of_dicts = user_record_with_attributes.get("assigned_apps")

            if not isinstance(attributes_list_of_dicts, list):
                continue

            extracted_attr_names = []
            for attr_dict in attributes_list_of_dicts: # Iterate the nested list of dictionaries
                if isinstance(attr_dict, dict):
                    # Extract a specific field from the inner dict (e.g., 'label' or 'name' for applications)
                    # The key for the name/label should be flexible.
                    attr_name = attr_dict.get("attr_name") # Example key
                    if not attr_name:
                        attr_name = attr_dict.get("label") # Common key for app name
                    if not attr_name:
                        attr_name = attr_dict.get("name")  # Another common key for app name
                    if not attr_name: # Try profile.name if it's a more complex app object
                        profile_info = attr_dict.get("profile")
                        if isinstance(profile_info, dict):
                            attr_name = profile_info.get("name")
                    
                    if attr_name:
                        extracted_attr_names.append(attr_name)
            
            if record_user_id not in user_to_attribute_names_map:
                user_to_attribute_names_map[record_user_id] = []
            # Add only unique attribute names for this user
            for name in extracted_attr_names:
                if name not in user_to_attribute_names_map[record_user_id]:
                    user_to_attribute_names_map[record_user_id].append(name)


        # Now, build the final items list using primary user data (e.g., from login events or a user list step),
        # filtering if necessary, and enriching with attributes from the map we just built.
        # For this example, we'll iterate through users_group1_raw again, assuming it's the primary list of users.
        # The agent should identify the correct step in `full_results` that contains the primary user list.
        primary_user_list_source = users_group1_raw # In a real scenario, this might be full_results.get("3")

        for user_g1_data in primary_user_list_source:
            if not isinstance(user_g1_data, dict):
                continue

            current_user_id = user_g1_data.get("user_id")
            if not current_user_id: # Fallback for user ID
                current_user_id = user_g1_data.get("id")
            # If user ID is in a nested structure like 'actor' (common in event logs)
            if not current_user_id:
                actor_info = user_g1_data.get("actor")
                if isinstance(actor_info, dict):
                    current_user_id = actor_info.get("id")
            
            if not current_user_id:
                continue # Skip if no identifiable ID

            # Filter: Skip if user is in the second group (if users_group2_raw was populated and relevant)
            if group2_user_ids_for_filtering and current_user_id in group2_user_ids_for_filtering:
                continue

            profile = user_g1_data.get("profile", {{}})
            if not isinstance(profile, dict): # If profile is not a dict, try to get info from actor
                actor_info = user_g1_data.get("actor", {{}})
                profile = {{ # Reconstruct a profile-like object from actor
                    "displayName": actor_info.get("displayName"),
                    "alternateId": actor_info.get("alternateId") 
                    # Add other mappings if actor has more relevant fields
                }}

            # Get processed attributes for this user from the map
            final_attribute_names = user_to_attribute_names_map.get(current_user_id, [])
            attributes_str = ", ".join(final_attribute_names) if final_attribute_names else "N/A"

            # Determine best name to display, being flexible with source (profile or actor)
            display_name = profile.get("displayName", "")
            first_name = profile.get("firstName", "")
            last_name = profile.get("lastName", "")
            email = profile.get("email", "") or profile.get("alternateId", "") # Use alternateId as fallback for email
            login = profile.get("login", "")
            
            name_to_display = "Unknown"
            if display_name: name_to_display = display_name
            elif first_name and last_name: name_to_display = f"{{first_name}} {{last_name}}"
            elif first_name: name_to_display = first_name
            elif last_name: name_to_display = last_name
            elif email: name_to_display = email 
            elif login: name_to_display = login
            elif current_user_id: name_to_display = current_user_id # Fallback to ID if no name
            
            items.append({{
                "name": name_to_display,
                "email": email or login or "N/A",
                "status": user_g1_data.get("status", "Unknown"), # Assuming status is top-level in user_data
                "user_id": current_user_id,
                "attributes_summary": attributes_str # Changed field name for clarity
            }})

        # --- Result Formatting ---
        headers = [
            {{"text": "User Name", "value": "name", "sortable": True, "align": "start"}},
            {{"text": "Email", "value": "email", "sortable": True, "align": "start"}},
            {{"text": "Account Status", "value": "status", "sortable": True, "align": "start"}},
            {{"text": "User ID", "value": "user_id", "sortable": True, "align": "start"}},
            {{"text": "Attributes Summary", "value": "attributes_summary", "sortable": True, "align": "start"}} # New header
        ]
            
        result = {{
            "display_type": "table",
            "content": items,
            "metadata": {{
                "headers": headers,
                "totalItems": len(items),
                "description": f"Users from the primary list (potentially filtered), with a summary of their complex attributes/applications."
            }}
        }}
        print(f"DEBUG: Result keys: {{list(result.keys()) if isinstance(result, dict) else 'N/A'}}")
        </CODE>
        
                **CRITICAL**:
        - When processing data from steps that return lists of dictionaries (e.g., a list of users, where each user dictionary might contain a list of their applications or attributes), pay close attention to the exact key names used in the full_results data. For example, a user identifier might be id, user_id, or actor.id depending on the source step. Your generated code must use the correct key present in the data.
        - The example code demonstrates common patterns. You MUST adapt these patterns to the specific structure and key names found in the full_results for the current query. Use the debug prints of full_results to guide your key selection.
        
        NOTES:
        - Your code will have access to a 'full_results' variable containing all execution results
        - Keys in full_results are step numbers: "1", "2", "3", etc.
        - Always check if an item is a list before trying to access its first element
        - Always extract entity names from the data instead of hardcoding specific names
        - Your code must create a 'result' variable with the final output
        - The result must have keys: display_type, content, and metadata
        - Choose display_type as either "markdown" or "table" (not both)
        - For tables, the 'result' variable should follow "EXAMPLE 2 - TABLE FORMAT (VUE-COMPATIBLE)" from the main system prompt (i.e., 'content' is the items array, 'metadata.headers' contains header definitions with 'text' and 'value').
        - For markdown, content should be a formatted string
        - Include useful metadata such as totalItems for the number of records processed
        
        IMPORTANT: Place your code ONLY between <CODE> and </CODE> tags.
        DO NOT use markdown code blocks or other formatting.
        

        """

# Create a singleton instance
results_processor = ResultsProcessorAgent()