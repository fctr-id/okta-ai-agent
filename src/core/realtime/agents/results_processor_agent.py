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
from src.core.model_picker import ModelConfig, ModelType
from src.utils.logging import get_logger
from src.utils.security_config import ALLOWED_SDK_METHODS, ALLOWED_UTILITY_METHODS
from src.core.model_picker import ModelConfig, ModelType
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
        
        IMPORTANT: Markdown is only usefule when you need to provide a summary or explanation. Otherwise , you can just pass the data as provided to you in the table format.
        
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
          "content": {
            "headers": [
              {
                "align": "start",
                "key": "name",
                "sortable": true,
                "title": "User Name"
              },
              {
                "key": "email",
                "sortable": true,
                "title": "Email Address"
              },
              {
                "key": "status",
                "sortable": true,
                "title": "Account Status"
              },
              {
                "key": "groups",
                "sortable": false,
                "title": "Group Memberships"
              }
            ],
            "items": [
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
            ]
          },
          "metadata": {{}}
        }
        
        For TABLE FORMAT, the structure exactly matches a Vue.js data table component:
        - "content" contains both "headers" and "items" arrays . It SHOULD be be a JSON object with: content: {'headers': [], 'items': []} as shown above
        - "headers" defines each column with key, title, alignment, and sortability
        - "items" contains the data rows as an array of objects
        - Each row property name must match a header key
        
        WHEN TO USE MARKDOWN:
        - When you have the "FULL" dataset and the user's original query is something you can answer with a summary in markdown
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
        
        CRITICAL OUTPUT FORMAT REQUIREMENT: 
        For table format, you MUST structure your response with both "headers" and "items" arrays 
            INSIDE the "content" object. DO NOT use a top-level "columns" array.
        
        Always prioritize clarity and directness in answering the user's query.
        """
        
        # Get the REASONING model since that's more appropriate for data formatting
        model = model_config or ModelConfig.get_model(ModelType.REASONING)
        
        # Create the agent with the system prompt, model, and output type
        self.agent = Agent(
            system=system_prompt,
            model=model  
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
         # Results Processing Task
                
        ## Original User Query
        {query}
                
        ## Execution Plan Reasoning
        {plan_reasoning}
                
        ## Complete Execution Results
        {results_str}
                
       ## Your Task
        Process these results and format them to directly answer the user's query. 
                
        Return your response in JSON format with:
        1. A display_type of either "markdown" or "table" (choose one)
        2. Content formatted according to the chosen display type
        
        ## Display Type Selection Guidelines
        Choose the most readable and useful display format. Consider the number of items, complexity of data, and the nature of the user's query.

        **1. MARKDOWN is generally preferred for:**
           *   **Small Datasets (5 or fewer items):**
               *   When displaying **5 or fewer items** (e.g., users, groups, log entries, etc.).
               *   If the items are verbose (e.g., detailed JSON objects like individual raw log events), present each item clearly within the markdown. This could be as formatted code blocks for each JSON, or a summarized list of key-value pairs for each item.
           *   **Summaries & Narratives:**
               *   Creating a brief summary with a few key points (typically less than 5 key points in total).
               *   Presenting hierarchical or deeply nested information that does not naturally fit a flat tabular structure, especially when item count is low.
               *   Creating a narrative explanation or answering "why" or "how" questions.
               *   Showing statistical summaries or aggregated insights.

        **2. TABLES are generally preferred for:**
           *   **Larger Datasets of Entities (more than 5 items):**
               *   When displaying **more than 5 items** that are lists of entities (e.g., users, applications, groups, log entries) where items share common attributes suitable for columns.
           *   **Structured Comparison Focus:**
               *   When the data, even if few items, primarily benefits from direct, column-by-column comparison, sorting, or clear columnar organization (e.g., a list of product SKUs, prices, and stock levels).
           *   **User Request for Tabular Format:** If the user's query explicitly asks for a table or implies a need for columnar data (e.g., "list users with columns for email and status").

        **3. Specific Guidance for Lists of Entities (users, apps, groups, logs, etc.):**
            *   If the list contains **5 or fewer entities**:
                *   Default to **MARKDOWN**. Present each entity's information clearly and fully. For example, for 3 log entries, you might list the key details of each log sequentially in markdown, or show each complete JSON object in a formatted code block.
            *   If the list contains **more than 5 entities**:
                *   Default to **TABLE** format.
                *   **Column Selection for Tables from Verbose Objects:** For entities with many fields (like verbose log objects), you MUST select a set of the most **common, important, and representative fields** for the table `headers`. The goal is to make the table initially readable and useful, not excessively wide.
                *   The `items` array in the table content, however, should still contain the **complete, unmodified data objects** for each item. The headers guide the display, but the full data remains available in each item object.

        ## Critical Results Requirements
        - NEVER limit the number of items (rows) displayed in either format.
        - ALWAYS include ALL items (rows) in your response regardless of format.
        - NEVER include notes about "showing only a subset" of items (rows).
        - NEVER use phrases like "first few results" or "due to space" when referring to the number of items (rows).
        - For tables: 
            - Include all items (rows) in the "items" array.
            - As per guideline 3, `headers` may be a selection of fields for readability if objects are verbose, but each object in the `items` array must be the complete, original data for that item.
        - For markdown: List all relevant items (rows) without truncation.
        
        ## Response Format Requirements
        - Return a dict with keys: `display_type`, `content`, and `metadata`.
        - For tables, `content` MUST be a dictionary with "headers" and "items" arrays:
          - `headers`: An array of column definition objects. Each object MUST have `key` (string, corresponding to a property in the item objects) and `title` (string, for display). It MAY also have `align` (e.g., "left", "right", "center") and `sortable` (boolean).
          - `items`: An array of the **complete data objects** as received or processed. The properties referenced by `header.key` must exist in these objects.
        - For markdown, `content` should be a single formatted string.
        - Include useful `metadata` such as:
          - `totalItems`: total number of records/items processed and included in the `content`.
          - `queryTime`: (Optional if available) processing time in milliseconds.
        - Answer the user's query thoroughly with all available relevant information.
        - If the answer is ambiguous or depends on factors not known, you may start your markdown content with 'It depends...' or similar, followed by the explanation.
        
        DO NOT wrap your JSON response in markdown code blocks or add any extra text.
        Response should be ONLY the JSON object without any extra characters.
        EXTRA IMPORTANT: Ensure the generated JSON response itself is valid and does not contain unescaped characters or formatting issues that would break JSON parsing, especially when dealing with data that might have come from large datasets.
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
        # Start by debugging the structure to understand what we're working with
        print(f"DEBUG: full_results keys: {{list(full_results.keys())}}")
        for key in full_results:
            print(f"DEBUG: full_results[{{key}}] type: {{type(full_results[key]).__name__}}")
            if isinstance(full_results[key], list):
                print(f"DEBUG: full_results[{{key}}] has {{len(full_results[key])}} items")
        
        # Extract data from Step 1 - Handle both list and direct object cases
        group1_data = full_results.get("1", [])
        # Access the group - handle case where it might be a list or direct object
        if isinstance(group1_data, list) and len(group1_data) > 0:
            group1 = group1_data[0]  # Get first item if it's a list
        else:
            group1 = group1_data  # Use directly if not a list
        
        # Extract data from Step 2 - Handle both list and direct object cases
        group2_data = full_results.get("2", [])
        if isinstance(group2_data, list) and len(group2_data) > 0:
            group2 = group2_data[0]  # Get first item if it's a list
        else:
            group2 = group2_data  # Use directly if not a list
        
        # Extract group names dynamically (never hardcode names)
        group1_name = group1.get("profile", {{}}).get("name", "First Group") if isinstance(group1, dict) else "First Group"
        group2_name = group2.get("profile", {{}}).get("name", "Second Group") if isinstance(group2, dict) else "Second Group"
        
        # Get user lists - these should always be lists
        users1 = full_results.get("3", [])
        users2 = full_results.get("4", [])
        
        # Collect all users in the second group by their IDs
        group2_user_ids = []
        for user in users2:
            if isinstance(user, dict) and "id" in user:
                user_id = user.get("id")
                if user_id and user_id not in group2_user_ids:
                    group2_user_ids.append(user_id)
        
        # Process users in first group and filter out those in second group
        items = []
        for user in users1:
            if not isinstance(user, dict):
                continue
                
            user_id = user.get("id", "")
            
            # Skip if user is in the second group
            if user_id in group2_user_ids:
                continue
                
            profile = user.get("profile", {{}})
            
            # Extract user information
            user_info = {{}}
            display_name = profile.get("displayName", "")
            first_name = profile.get("firstName", "")
            last_name = profile.get("lastName", "")
            email = profile.get("email", "")
            login = profile.get("login", "")
            
            # Determine best name to display
            if display_name:
                user_info["name"] = display_name
            elif first_name and last_name:
                user_info["name"] = f"{{first_name}} {{last_name}}"
            elif first_name:
                user_info["name"] = first_name
            elif last_name:
                user_info["name"] = last_name
            elif email:
                user_info["name"] = email
            elif login:
                user_info["name"] = login
            else:
                user_info["name"] = "Unknown"
                
            # Other user information
            user_info["email"] = email or login or "Unknown"
            user_info["status"] = user.get("status", "Unknown")
            user_info["id"] = user_id
            
            # Add to our results
            items.append(user_info)
        
        # Define headers for the table - Vue.js format
        headers = [
            {{
                "align": "start",
                "key": "name",
                "sortable": True,
                "title": "User Name"
            }},
            {{
                "key": "email",
                "sortable": True,
                "title": "Email"
            }},
            {{
                "key": "status",
                "sortable": True,
                "title": "Account Status"
            }},
            {{
                "key": "id",
                "sortable": True,
                "title": "User ID"
            }}
        ]
            
        # Create the final result structure with dynamic description
        result = {{
            "display_type": "table",
            "content": {{
                "headers": headers,
                "items": items
            }},
            "metadata": {{
                "totalItems": len(items),
                "description": f"Users in 'group1_name' group but NOT in 'group2_name' group"
            }}
        }}
        </CODE>
        
        NOTES:
        - Your code will have access to a 'full_results' variable containing all execution results
        - Keys in full_results are step numbers: "1", "2", "3", etc.
        - Always check if an item is a list before trying to access its first element
        - Always extract entity names from the data instead of hardcoding specific names
        - Your code must create a 'result' variable with the final output
        - The result must have keys: display_type, content, and metadata
        - Choose display_type as either "markdown" or "table" (not both)
        - For tables, content MUST be a dictionary with "headers" and "items" arrays
        - For markdown, content should be a formatted string
        - Include useful metadata such as totalItems for the number of records processed
        
        IMPORTANT: Place your code ONLY between <CODE> and </CODE> tags.
        DO NOT use markdown code blocks or other formatting.
        """

# Create a singleton instance
results_processor = ResultsProcessorAgent()