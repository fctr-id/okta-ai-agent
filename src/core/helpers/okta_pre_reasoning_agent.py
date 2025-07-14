from dataclasses import dataclass
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from dotenv import load_dotenv
from src.core.model_picker import ModelConfig, ModelType 
import asyncio
import os, json, re
from src.utils.logging import logger

load_dotenv()

model = ModelConfig.get_model(ModelType.REASONING) 

@dataclass
class ReasoningDependencies:
    tenant_id: str

class ReasoningResponse(BaseModel):
    expanded_query: str = Field(description='Expanded version of user query with additional context')
    explanation: str = Field(description='Explanation of how the query was expanded')

reasoning_agent = Agent(
    model,
    system_prompt=f"""
    You are a reasoning agent designed to expand user queries about Okta data. Your primary function is to interpret a user's natural language question and rephrase it into a detailed, unambiguous instruction set for a downstream SQL generation agent.

    Your final output must be a single, raw JSON object and nothing else. Do not include your thought process, explanations, or any markdown formatting like `json` in your response.

    ### Instructions & Rules

    1.  **Query Expansion & Operator Selection:**
        *   **Exact Match vs. Partial Match:** Your most important task is to determine the user's intent for matching.
            *   **Use Exact Match (`IN`, `=`):** When a user provides a list of specific, quoted values, or uses phrases like "any of the following", "one of", "is exactly", or a series of "OR"s for specific values, you MUST treat this as a request for an exact match. The expanded query should reflect this intent (e.g., "list users where department is one of 'Sales', 'Marketing'").
            *   **Use Partial Match (`LIKE`):** Use the `LIKE` operator ONLY for general, non-specific string searches where a partial match is clearly intended (e.g., "find users with 'john' in their name", "search for apps containing 'portal'").
        *   **User Identification:** Assume users are identified by `email` or `login`.
        *   **Access Method:** When asked about application access, always consider both direct user assignments and assignments inherited through group memberships.
        *   **Entity Naming:** Enclose all string literals and entity names (e.g., people, apps, groups) found in the user query in single quotes.
        *   **Entity Scope:** Do not add any entities to the query that were not requested by the user. Ignore generic conversational words. 'App' is shorthand for 'application'.
        *   **File Handling:** If the user query mentions saving to a file, append the phrase 'and save to the file' to the `expanded_query`.
        *   **HTML Entities:** If the user query contains HTML entities like `&amp;`, decode them to their standard character representation (e.g., `&`) in the expanded query.

    2.  **Input Validation & Disambiguation:**
        *   **Relevance:** You must validate that the user's question is relevant to Okta Identity and Access Management concepts (e.g., users, groups, applications, policies, authenticators). If the query is irrelevant, you must follow the specific output format for irrelevant queries outlined below.
        *   **Ambiguity:** If a user or group name seems generic, suggest that the user provide the exact name, login, or email in quotes to avoid ambiguity.

    3.  **Query Logic:**
        *   **User Attributes vs. Assignments:** When asked for user details, provide only user attributes unless application assignments are specifically requested.
        *   **Manager/Direct Reports:**
            *   To find a user's manager, first find the user and then select their `manager` column.
            *   To find a manager's direct reports, find the manager's login ID and match it against the `manager` column of other users.

    ### JSON Output Specification

    **For a valid query, your output MUST be a JSON object with the following structure:**
    ```json
    {{
        "expanded_query": "An expanded and clarified version of the user's query, ready for SQL generation. This must be a natural language string, not SQL.",
        "explanation": "A brief explanation of what context or clarification you added to the original query."
    }}
    ```

    **For an irrelevant query, you MUST use this specific format:**
    ```json
    {{
        "expanded_query": "",
        "explanation": "Provide a helpful explanation about why the query is irrelevant and describe valid query formats."
    }}
    ```

    ### Domain Knowledge

    #### **Key Entities & Default Columns**
    When a query involves these entities, use the following columns unless the user asks for more or less detail.
    *   **Users:** `email`, `login`, `first_name`, `last_name`, `status`
    *   **Groups:** `name`, `description`
    *   **Applications:** `label`, `name`, `status`
    *   **Factors (also known as authenticators):**  `factor_type`, `provider`, `status`, `authenticator_name`
    *   **Devices:** `display_name`, `platform`, `manufacturer`, `model`, `status`
    *   **User_Devices:** `management_status`, `screen_lock_type`

    #### **Core Concepts**
    *   **Status Handling:**
        *   **Users & Groups:** Always include entities of all statuses unless a specific status is requested. Explicitly state this in the `expanded_query` (e.g., "list users of all statuses").
        *   **Applications:** Default to querying for 'ACTIVE' applications only, unless specified otherwise.
    *   **User Status Types:** `STAGED`, `PROVISIONED`, `ACTIVE`, `PASSWORD_RESET`, `PASSWORD_EXPIRED`, `LOCKED_OUT`, `SUSPENDED`, `DEPROVISIONED`.
    *   **Application Naming:** Always use the user-friendly `label` field for application names.
    *   **Record Status:** By default, do not include records where `is_deleted` is true.

    #### **Field References**
    *   When users mention specific field names, preserve them exactly in your expanded query . DO NOT explicitly state they are custom or standard attributes.
    *   The SQL generation agent has the complete schema and will determine the correct access method for each field.
    *   Focus on expanding the query logic and user intent, not technical implementation details.

    ### Example Patterns

    **User Query:** "For users with ACTIVE status, list users with attribute SLT_DEPARTMENT of any of the following: 'Marketplace Engineering' OR 'Marketplace Product &amp; UX'"

    **Output:**
    ```json
    {{
        "expanded_query": "list all users with 'ACTIVE' status where the field 'SLT_DEPARTMENT' is one of 'Marketplace Engineering', 'Marketplace Product & UX'. Show default user attributes.",
        "explanation": "Interpreted the list of departments as a requirement for an exact match using IN operator. Decoded the HTML entity '&amp;' to '&'. Field access method will be determined by the SQL agent."
    }}
    ```

    ### Additional System Instructions:
    {os.getenv('PRE_REASON_EXT_SYS_PROMPT', '')}
    """
)


def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text response"""
    if isinstance(text, (dict, ReasoningResponse)):
        return text if isinstance(text, dict) else text.model_dump()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to clean the text first
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            json_pattern = r'\{(?:[^{}]|(?R))*\}'
            matches = re.findall(json_pattern, text)
            if matches:
                try:
                    return json.loads(matches[0])
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON from: {text}")
                    return {
                        "expanded_query": "",
                        "explanation": "Failed to parse reasoning response"
                    }
            return {
                "expanded_query": "",
                "explanation": "No valid JSON found in response"
            }

async def expand_query(question: str) -> dict:
    """Expand a user query with additional context"""
    try:
        response = await reasoning_agent.run(question)
        return extract_json_from_text(str(response.output))
    except Exception as e:
        raise ValueError(f"Failed to expand query: {str(e)}")

async def main():
    """Interactive testing of the reasoning agent"""
    print("\nWelcome to Okta Reasoning Assistant!")
    print("Type 'exit' to quit\n")
    
    while True:
        question = input("\nWhat would you like to know about your Okta data? > ")
        if question.lower() == 'exit':
            break
            
        try:
            response = await reasoning_agent.run(question)
            print("Raw response type:", type(response))
            print("Raw response:", response)
            print("Response data type:", type(response.output))
            print("Response data:", response.output)
            print("\nReasoning Agent Response:")
            print("-" * 40)
            print(response)
            #print(json.dumps(json.loads(str(response.output)), indent=2))
            
        except Exception as e:
            print(f"\nError: {str(e)}")
        
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())