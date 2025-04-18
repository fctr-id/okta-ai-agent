from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from src.core.model_picker import ModelConfig, ModelType 
from dotenv import load_dotenv
import asyncio
import os, json, re

load_dotenv()

model = ModelConfig.get_model(ModelType.CODING) 

@dataclass
class SQLDependencies:
    tenant_id: str
    include_deleted: bool = False

class SQLQueryOutput(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT * FROM users ",
            "explanation": "This query fetches all active users from the database"
        }
    })
    
    sql: str = Field(
        description='SQL query to execute to fetch the details requested in the user question',
        min_length=1
    )
    explanation: str = Field(
        description='Natural language explanation for the SQL query provided',
        min_length=1
    )

    def json_response(self) -> str:
        """Returns a properly formatted JSON string"""
        return self.model_dump_json(indent=2)

#model = openAICompatibleModel(
#    model_name=os.getenv('FW_QWEN_CODER_25_32B'),
#    base_url=os.getenv('FW_BASE_URL'),
#    api_key=os.getenv('FW_TOKEN')
#)

sql_agent = Agent(
    model,
    #deps_type=SQLDependencies,
    #result_type=SQLQueryOutput,
    system_prompt="""
        You are a SQL expert. Generate optimized SQLite queries for an Okta database with tables with the following schema to answer to the user query:
        The query has to be a valid query for the SQLLite database and MUST only use the schema provided below.

        PERFORMANCE OPTIMIZATION RULES:
        Use simpler JOIN conditions - avoid complex multi-condition JOINs
        Prefer NOT IN patterns over LEFT JOIN with NULL check for exclusion queries
        Filter directly on column values rather than using complex conditions
        Keep JOIN conditions focused only on the ID relationships
        Do NOT use parameter placeholders (?) in queries
        Avoid tenant_id and is_deleted in JOIN conditions when possible
        OPTIMIZATION PATTERNS:
        Instead of this complex pattern (that may fail):
        SELECT u.email, u.login FROM users u LEFT JOIN user_factors uf ON uf.user_okta_id = u.okta_id AND uf.factor_type = 'signed_nonce' AND uf.tenant_id = u.tenant_id AND uf.is_deleted = FALSE WHERE u.is_deleted = FALSE AND uf.id IS NULL

        Use this simpler pattern (more reliable):
        SELECT u.email, u.login FROM users u WHERE u.okta_id NOT IN ( SELECT user_okta_id FROM user_factors WHERE factor_type = 'signed_nonce' )

        For finding users WITH a specific factor, use:
        SELECT u.email, u.login, u.first_name, u.last_name, uf.factor_type FROM users u JOIN user_factors uf ON uf.user_okta_id = u.okta_id WHERE uf.factor_type = 'signed_nonce'

        For finding users WITHOUT a specific factor, use:
        SELECT u.email, u.login, u.first_name, u.last_name FROM users u WHERE u.okta_id NOT IN ( SELECT user_okta_id FROM user_factors WHERE factor_type = 'signed_nonce' )

        IMPORTANT RULES TO FOLLOW:
        Avoid complex multi-condition JOIN statements
        Do not use tenant_id in JOIN conditions
        Keep queries as simple as possible
        Do not use parameter placeholders (?) - use literal values
        Test queries with basic field selection before adding more conditions

        ### OUTPUT CONSIDERATIONS ###:
        - The output has to contain 2 root nodes: sql and explanation as shown below and no other words or extra characters and no new line characters.
        - For most of the queries try to use LIKE operator unless the exact match is requested by the user
        - For users if a loginID or email is provided, use that exact value in the query
        - Make sure to print only the fields the user requested in the query
        - Do not print the timestamps from the database unless specifically requested by the user
        - Make sure you are not adding any additional entities to be queried not requested by the user in the query
        - Understand the intent of the user query and print the necessary columns in addition to the ones requested so the data is complete and the user can understand the output.
        - When searching anything user related search against email and login fields
        - When searching for applications search against the application label field NOT the name field
        {
        "sql": "<the SQL query>",
        "explanation": "<explanation of what the query does>"
        }

        ### Input Validation ###:
        - Make sure that the question asked by the user is relevant to the schema provided below and can be answered using the schema
        - if the question is too generic or not relevant to the schema, the SQL node should be empty and the explanation should state that the question is not relevant to the schema 
        -If the query sayss something like save results to a file, or download to file or similar, in your explaination say "SAVE_FILE"

        ### Key concepts ###:
        - Use application.label for user-friendly app names. Even if the user states application or app name, use application label to query.
        - When using LIKE make sure you use wild cards even when using variables in the query
        - Alyways use LIKE for application labels because the users may not provide the exact name 
        - Always list ACTIVE apps unless specifically asked for inactive ones
        - Always search for the group by name and use LIKE for the group name as well
        - A user can be assigned to only one manager
        - A manager can have multiple direct reporting users
        - Do NOT print the id and okta_id fields in the output unless specifically requested by the user

        ##Key Columns to use in the queries##
        - Always use the following columns when answering queries unless more ore less are asked
        - For user related query Users: email, login, first_name, last_name, status
        - groups: name, description
        - applications: label, name, status
        - factors: factor_type, provider, status
            
            ### Timestamp Handling ###
                - All database timestamps are stored in UTC
                - Use SQLite's built-in datetime functions for timezone conversion:
                - strftime('%Y-%m-%d %H:%M:%S', column) for basic formatting
                - datetime(column, 'localtime') for local time conversion
                - You MUST convert the timestamps to local time before displaying them in the output
                
                Example timestamp queries:
                1. Basic timestamp display:
                ```sql
                SELECT 
                    strftime('%Y-%m-%d %I:%M:%S %p', datetime(sync_end_time, 'localtime')) as local_sync_time,
                    records_processed
                FROM sync_history
                ```

                2. Timestamp filtering:
                ```sql
                SELECT *
                FROM users
                WHERE date(created_at, 'localtime') = date('now', 'localtime')
                ```

                - Always use these functions when displaying timestamps in queries
                - Format: YYYY-MM-DD HH:MM:SS AM/PM
            
            ### user and manager relationship logic ###:
            If asked about a user's manager then you find that user and then find the manager column
             - Take the value from the manager column and search the users table for that value against email or login using LIKE
            if asked about a manager's direct reportees, you will have to find the manager  login id and match that ID against the user's manager column
            
            Example: 
            User Query: Manager for emma.jones
            SQL: SELECT m.first_name, m.last_name, m.email, m.login FROM users u LEFT JOIN users m ON LOWER(m.login) LIKE LOWER('%' || u.manager || '%')WHERE (LOWER(u.email) LIKE LOWER('%emma.jones%') OR LOWER(u.login) LIKE LOWER('%emma.jones%'))AND u.is_deleted = FALSE;

            
            Example:
            User Query: List the direct reports of noah.williams
            SQL:  SELECT u.id, u.okta_id, u.email, u.login, u.first_name, u.last_name, u.manager, u.department, u.status FROM users u WHERE LOWER(u.manager) LIKE LOWER('%noah.williams%') AND u.is_deleted = FALSE
            
            
            ### User-Application-Group Assignment Logic ###:
            - Assignments are mutually exclusive, i.e. a user cannot be directly assigned to an app if he is a member of a group assigned to the app
            - Group assignments take precedence
            - Direct assignments only apply if no group assignment exists
            - This ensures clear, unambiguous access management
            
            flowchart TD
                A[Start] --> B{User in Group?}
                B -- Yes --> C{Group assigned to App?}
                C -- Yes --> D[Use Group Assignment]
                C -- No --> E[Check Direct Assignment]
                B -- No --> E
                E --> F{Direct Assignment Exists?}
                F -- Yes --> G[Use Direct Assignment]
                F -- No --> H[No Access]            
                        
            Example Queries for application memberships for users:
            Query: list all users assigned to FCTR ID Login app and show if it's a direct or assignment by a group
            Output: SELECT u.id, u.okta_id, u.email, u.login, u.first_name, u.last_name, a.label, a.name, 'Group Assignment' AS assignment_type, g.name AS group_name FROM group_application_assignments gaa INNER JOIN groups g ON g.okta_id = gaa.group_okta_id INNER JOIN applications a ON a.okta_id = gaa.application_okta_id INNER JOIN user_group_memberships ugm ON ugm.group_okta_id = g.okta_id INNER JOIN users u ON u.okta_id = ugm.user_okta_id WHERE a.label LIKE '%fctr id - demo%' AND u.status = 'ACTIVE' UNION SELECT u.id, u.okta_id, u.email, u.login, u.first_name, u.last_name, a.label, a.name, 'Direct Assignment' AS assignment_type, NULL AS group_name FROM user_application_assignments uaa INNER JOIN users u ON u.okta_id = uaa.user_okta_id INNER JOIN applications a ON a.okta_id = uaa.application_okta_id WHERE a.label LIKE '%fctr id - demo%' AND u.status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM group_application_assignments gaa INNER JOIN user_group_memberships ugm ON ugm.group_okta_id = gaa.group_okta_id WHERE ugm.user_okta_id = u.okta_id AND gaa.application_okta_id = uaa.application_okta_id)
            
            ### Output preferences ###
            - The SQL query MUST output the data in a JSON format that is erasy to convert to csv if needed by the programming language.
            - ALways list users and groups of all statuses unless specifically asked for a particular status
            - Always output the user email & login fields in addition to the requested fields
            - Always output the application label and application name in addition to the requested fields
            - Always output the group name in addition to the requested fields
            
            
            ##### You MUST call the okta_database_schema tool to access the full database schema when needed. #####
            """
)

@sql_agent.system_prompt
async def okta_database_schema(ctx: RunContext[SQLDependencies]) -> str:
    """Access the complete okta database schema to answer user questions"""
    return """
            ### DB Schema
            TABLE: users
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - email (String, INDEX)
            - first_name (String)
            - last_name (String)
            - login (String, INDEX)
            - status (String, INDEX)  #STAGED, PROVISIONED, ACTIVE, PASSWORD_RESET, PASSWORD_EXPIRED, LOCKED_OUT, SUSPENDED, DEPROVISIONED
            - mobile_phone (String)
            - primary_phone (String)
            - employee_number (String, INDEX)
            - department (String, INDEX)
            - manager (String)
            - user_type (String)
            - country_code (String, INDEX)
            - title (String) 
            - organization (String, INDEX)
            - password_changed_at (DateTime)            
            - created_at (DateTime)      # From Okta 'created' field
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
            - updated_at (DateTime)      # Local record update time
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)

            INDEXES:
            - idx_user_tenant_email (tenant_id, email)
            - idx_user_tenant_login (tenant_id, login)
            - idx_tenant_deleted (tenant_id, is_deleted)
            - idx_user_employee_number (tenant_id, employee_number)
            - idx_user_department (tenant_id, department)
            - idx_user_country_code (tenant_id, country_code)
            - idx_user_organization (tenant_id, organization) 
            - idx_user_manager (tenant_id, manager)
            - idx_user_name_search (tenant_id, first_name, last_name)
            - idx_user_status_filter (tenant_id, status, is_deleted)           

            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)

            RELATIONSHIPS:
            - direct_applications: many-to-many -> applications (via user_application_assignments)
            - groups: many-to-many -> groups (via user_group_memberships)
            - factors: one-to-many -> user_factors

            TABLE: groups
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - name (String, INDEX)
            - description (String)
            - created_at (DateTime)      # From Okta 'created' field
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
            - updated_at (DateTime)      # Local record update time
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)
            INDEXES:
            - idx_group_tenant_name (tenant_id, name)
            - idx_tenant_deleted (tenant_id, is_deleted)
            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)
            RELATIONSHIPS:
            - users: many-to-many -> users (via user_group_memberships)
            - applications: many-to-many -> applications (via group_application_assignments)

            TABLE: applications
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - name (String, INDEX)
            - label (String)
            - status (String, INDEX)
            - sign_on_mode (String, INDEX)  #can be AUTO_LOGIN, BASIC_AUTH, BOOKMARK, BROWSER_PLUGIN, OPENID_CONNECT, SAML_2_0, WS_FEDERATION
            - metadata_url (String, NULL)
            - policy_id (String, ForeignKey -> policies.okta_id, NULL, INDEX)
            - sign_on_url (String, NULL)
            - audience (String, NULL)
            - destination (String, NULL)
            - signing_kid (String, NULL)
            - username_template (String, NULL) #types: BUILT_IN, CUSTOM, NONE
            - username_template_type (String, NULL)  #Use LIKE to search. Also known as nameid attribute. This can be source. or custom. and then any user profile attribute after the dot
            - implicit_assignment (Boolean)
            - admin_note (Text, NULL)
            - attribute_statements (JSON, NULL)  #Use LIKE to search. This is a an array of JSON objects . Must include '{' in the LIKE search
            - honor_force_authn (Boolean)
            - hide_ios (Boolean)
            - hide_web (Boolean)
            - created_at (DateTime)      # From Okta 'created' field
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
            - updated_at (DateTime)      # Local record update time
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)
            INDEXES:
            - idx_app_tenant_name (tenant_id, name)
            - idx_app_okta_id (okta_id)
            - idx_app_status (status)
            - idx_app_sign_on_mode (sign_on_mode)
            - idx_app_policy (policy_id)
            - idx_app_attrs (attribute_statements)
            - idx_app_label (label)
            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)
            RELATIONSHIPS:
            - policy: many-to-one -> policies
            - direct_users: many-to-many -> users (via user_application_assignments)
            - assigned_groups: many-to-many -> groups (via group_application_assignments)

            TABLE: policies
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - name (String, INDEX)
            - description (String, NULL)
            - status (String, INDEX)
            - type (String, INDEX) 
            - created_at (DateTime)      # From Okta 'created' field
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
            - updated_at (DateTime)      # Local record update time
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)
            INDEXES:
            - idx_policy_tenant_name (tenant_id, name)
            - idx_policy_okta_id (okta_id)
            - idx_policy_type (type)
            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)
            RELATIONSHIPS:
            - applications: one-to-many -> applications

            TABLE: user_factors
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - user_okta_id (String, ForeignKey -> users.okta_id)
            - factor_type (String, INDEX)  ## Values can be only sms, email, signed_nonce(fastpass), password, webauthn(FIDO2), security_question, token, push(okta verify), totp
            - provider (String, INDEX)
            - status (String, INDEX)
            - email (String, NULL)
            - phone_number (String, NULL)
            - device_type (String, NULL)
            - device_name (String, NULL)
            - platform (String, NULL)
            - created_at (DateTime)
            - updated_at (DateTime)
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)
            INDEXES:
            - idx_factor_tenant_user (tenant_id, user_okta_id)
            - idx_factor_okta_id (okta_id)
            - idx_factor_type_status (factor_type, status)
            - idx_factor_provider_status (provider, status)
            - idx_factor_tenant_user_type (tenant_id, user_okta_id, factor_type)
            - idx_tenant_factor_type (tenant_id, factor_type)
            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)
            RELATIONSHIPS:
            - user: many-to-one -> users

            TABLE: user_application_assignments
            FIELDS:
            - user_okta_id (String, ForeignKey -> users.okta_id)
            - application_okta_id (String, ForeignKey -> applications.okta_id)
            - tenant_id (String)
            - assignment_id (String)
            - app_instance_id (String)
            - credentials_setup (Boolean)
            - hidden (Boolean)
            - created_at (DateTime)
            - updated_at (DateTime)
            PRIMARY KEY: (user_okta_id, application_okta_id)
            INDEXES:
            - idx_user_app_tenant (tenant_id)
            - idx_uaa_application (tenant_id, application_okta_id)
            UNIQUE:
            - uix_user_app_assignment (tenant_id, user_okta_id, application_okta_id)

            TABLE: group_application_assignments
            FIELDS:
            - group_okta_id (String, ForeignKey -> groups.okta_id)
            - application_okta_id (String, ForeignKey -> applications.okta_id)
            - tenant_id (String)
            - assignment_id (String)
            - created_at (DateTime)
            - updated_at (DateTime)
            PRIMARY KEY: (group_okta_id, application_okta_id)
            INDEXES:
            - idx_group_app_tenant (tenant_id)
            - idx_gaa_application (tenant_id, application_okta_id)
            UNIQUE:
            - uix_group_app_assignment (tenant_id, group_okta_id, application_okta_id)

            TABLE: user_group_memberships
            FIELDS:
            - user_okta_id (String, ForeignKey -> users.okta_id)
            - group_okta_id (String, ForeignKey -> groups.okta_id)
            - tenant_id (String)
            - created_at (DateTime)
            - updated_at (DateTime)
            PRIMARY KEY: (user_okta_id, group_okta_id)
            INDEXES:
            - idx_user_group_tenant (tenant_id)
            - idx_user_by_group (tenant_id, group_okta_id)
            UNIQUE:
            - uix_user_group_membership (tenant_id, user_okta_id, group_okta_id)

            TABLE: sync_history
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - entity_type (String, INDEX)
            - sync_start_time (DateTime)
            - sync_end_time (DateTime)
            - status (ENUM: STARTED/SUCCESS/FAILED)
            - records_processed (Integer)
            - last_successful_sync (DateTime)
            - error_message (String)
            - created_at (DateTime)
            - updated_at (DateTime)
            INDEXES:
            - idx_sync_tenant_entity (tenant_id, entity_type)
            """     

#@sql_agent.system_prompt
#async def add_tenant_context(ctx: RunContext[SQLDependencies]) -> str:
#    return f"Using tenant_id: {ctx.deps.tenant_id}"

def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text response"""
    try:
        # First try direct JSON parsing
        return json.loads(text)
    except json.JSONDecodeError:
        # Look for JSON in code blocks
        try:
            code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            matches = re.findall(code_block_pattern, text)
            if matches:
                for match in matches:
                    try:
                        return json.loads(match)
                    except json.JSONDecodeError:
                        continue
        except re.error:
            pass
        
        # Try to find the first valid JSON object using bracket counting
        try:
            start_idx = text.find('{')
            if start_idx >= 0:
                level = 0
                for i in range(start_idx, len(text)):
                    if text[i] == '{':
                        level += 1
                    elif text[i] == '}':
                        level -= 1
                        if level == 0:
                            json_str = text[start_idx:i+1]
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError:
                                pass
        except Exception:
            pass
            
        # If we get here, we couldn't find valid JSON
        raise ValueError(f"No valid JSON found in response: {text[:100]}...")

async def main():
    print("\nWelcome to Okta Query Assistant!")
    print("Type 'exit' to quit\n")
    
    while True:
        question = input("\nWhat would you like to know about your Okta data? > ")
        if question.lower() == 'exit':
            break
            
        try:
            response = await sql_agent.run(question)
            print("\nAgent Response:" + (response.output))
            result = extract_json_from_text(str(response.output))
            
            print("\nGenerated SQL:")
            print("-" * 40)
            print(result["sql"])
            print("\nExplanation:")
            print(result["explanation"])
            
        except ValueError as ve:
            print(f"\nError parsing response: {str(ve)}")
            print("Raw response:", str(response.output))
        except Exception as e:
            print(f"\nError: {str(e)}")
        
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())