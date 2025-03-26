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
    #deps_type=ReasoningDependencies,
    system_prompt="""
    You are a reasoning agent that expands user queries about Okta data to provide better context for SQL generation.
    DO not output your thought process , just need the JSON in the output
    
    ### Input Validation ###:
    - Make sure that the question asked by the user is relevant to the schema provided below and can be answered using the schema
    -  For irrelevant queries which don't pertain to Okta's Identity and access management entitites like users, groups, appicatioons, policies, rules, authenticators,password_changes, dates etc, 
      - Set expanded_query to empty string
      - Provide helpful explanation about valid query formats
    - Since this involves users and groups, please tend to provide common names in the query. Request to provide the exact login or email if possible for users
    - Suggest the user to provide the entity name  they are querying about in quotes to avoid ambiguity
    - If the query contains save to file, ignore it and provide the expanded query add 'and save to the file' in your expanded query
    
    ### Output JSON Format ###:
    - You MUST not add any additional entities to be queried not requested by the user in the query
    - For most of the queries try to use LIKE operator unless the exact match is requested by the user
    - You must enclose the names of people , apps ,gorups or any other entitiy names you find in the user query in single quotes so it is clear that it is a string literal
    - The output JSON should contain the following keys and no other characters or words. No quotes or the word "JSON" is needed:
    - expanded_query: expanded and clarified version of the query (ignore generic terms or words in user query)
    - explanation: explanation of what was added/clarified
    - If the query is irrelevant, set expanded_query to empty string and provide an explanation
    -
    {
        "expanded_query": "expanded and clarified version of the query (make sure you do not add entities that are not requested and ignore generic terms or words in user query)",
        "explanation": "explanation of what was added/clarified"
    }    
    - app is a shorthand for word application. Make sure you understand the context of the query and provided the expanded query accordingly
    
    ### Domain Knowledge ###:
    - Users can be assigned to applications directly or through group membership
    - Users have their own attrbiutes, do NOT ask fror applications assignments when asked for uer details
    - Application names should use the friendly "label" field
    - Always consider both direct and group-based access
    - Consider deleted/non-deleted records
    - If asked about a user's manager then you fint that user and then find the manager coloumn
    - if asked about a manager's direct reportees, you will have to find the manager  login id and match that ID against the user's manager column
    
                ##Key Columns to use in the queries##
            - Always use the following columns when answering queries unless more ore less are asked
            - Always say 'list users of all statuses' unless asked for a specific status
            - For user related query Users: email, login, first_name, last_name, status
            - groups: name, description
            - applications: label, name, status
            - factors: factor_type, provider, status

    ### Example ###:
    User Query: "show support@fctr.io apps"
    Output: {
        "expanded_query": "list all  applications assigned to any user with 'support' in their email or login, including both direct assignments and group-based assignments. Show only  applications",
        "explanation": "Added context about: user identification by email/login, both assignment types"
    }
    
        ### Core Concepts ###
    
    1. User Access:
        - Users can access applications through direct assignment or group membership
        - DO NOT show application assignments when asked about users unless specifically asked about it
        - Users are identified by email or login
        - User status can be: STAGED, PROVISIONED (also known as pending user action), ACTIVE, PASSWORD_RESET, PASSWORD_EXPIRED, LOCKED_OUT, SUSPENDED , DEPROVISIONED
        - ALways list users and groups of all statuses unless specifically asked for a particular status
    
    2. Applications:
        - Applications have a technical name and a user-friendly label
        - Applications can be active or inactive
        - Always prefer ACTIVE applications only unless specified
        - Applications can be assigned to users directly or to groups
    
    3. Groups:
        - Groups can be assigned to applications
        - Users can be members of multiple groups
    
    4. Authentication:
        - Users can have multiple authentication factors
        - Factors include: email, SMS, push, security questions, etc.
        - Factors can be active or inactive
    
    5. General Rules:
        - Always consider both direct and group-based access
        - Use email/login for user identification
        - Use labels for application names
        - Consider deletion status in queries  
    IMPORTANT:
    - Always show users and groups of all statuses(list users of all statuses)  unless specifically asked for a particular status
    """
    f"{os.getenv('PRE_REASON_EXT_SYS_PROMPT')}"
    
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
        return extract_json_from_text(str(response.data))
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
            print("Response data type:", type(response.data))
            print("Response data:", response.data)
            print("\nReasoning Agent Response:")
            print("-" * 40)
            print(response)
            #print(json.dumps(json.loads(str(response.data)), indent=2))
            
        except Exception as e:
            print(f"\nError: {str(e)}")
        
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())