from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from dotenv import load_dotenv
import asyncio
import os
import json
import re

load_dotenv()

# Use the model picker approach from the working version
try:
    from src.core.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.REASONING)
except ImportError:
    # Fallback to simple model configuration
    def get_simple_model():
        """Simple model configuration without complex imports"""
        model_name = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
        return model_name
    model = get_simple_model()

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

# Replace the existing system_prompt content with this updated version:

sql_agent = Agent(
    model,
    output_type=SQLQueryOutput,
    deps_type=SQLDependencies,
    system_prompt="""
You are an expert-level SQLite engineer. Your primary task is to convert user requests into a single, optimized, and valid SQLite query based on the provided database schema. You must follow all rules and patterns outlined below without deviation.

### 1. CORE DIRECTIVE: OUTPUT FORMAT
Your final output MUST be a single, raw JSON object and nothing else. It must contain two keys: `sql` and `explanation`. Do not add any extra characters, newlines, or text outside of this JSON structure.

{
"sql": "<A SINGLE, VALID SQLITE QUERY STRING>",
"explanation": "<A CONCISE EXPLANATION OF THE QUERY. If the user asks to save or download, begin the explanation with 'SAVE_FILE'.>"
}

### 2. GOLDEN RULES (APPLY TO ALL QUERIES)
1.  **Single Query Only:** You MUST generate only one SQL query.
2.  **No Placeholders:** All values must be hardcoded literals. NEVER use `?`.
3.  **Schema is Truth:** The database schema provided below is the ONLY source of truth for table and column names. NEVER reference columns not explicitly listed in the schema.
4.  **No Assumed Columns:** Do NOT assume tables have `is_deleted`, `active`, or other columns unless explicitly listed in the schema. Only use columns that are documented.
5.  **Default Status Filter:** Unless the user specifies a different status (e.g., "inactive," "suspended"), you MUST filter for `status = 'ACTIVE'` for users, applications, and any other relevant entities.
6.  **Default Columns:**
    *   **Users:** ALWAYS include `email`, `login`, `first_name`, `last_name`, `status`. Also include `okta_id` if the query involves relationships (groups, apps, etc.).
    *   **Groups:** ALWAYS include `name`, `description`, `okta_id`.
    *   **Applications:** ALWAYS include `label`, `name`, `status`, `okta_id`.
    *   Never select timestamp columns unless explicitly requested.
7.  **Default Sorting:**
    *   For **users**, `ORDER BY last_name ASC, first_name ASC`.
    *   For **groups**, `ORDER BY name ASC`.
    *   For **applications**, `ORDER BY label ASC`.
    *   Only override these defaults if the user requests a different sort order.

### 3. QUERY GENERATION PROCESS (Follow these steps)

**Step 1: Input Validation**
*   If the user's question is generic or cannot be answered by the schema, set the `sql` value to `""` and explain why in the `explanation`.

**Step 2: Field & Operator Resolution (CRITICAL)**
*   **Check Schema First:** Before writing a `WHERE` clause, determine if the field is a standard column or a custom attribute.
    *   **Standard Columns:** `department`, `user_type`, `title`, `manager`, etc. Use direct column access (e.g., `WHERE department = 'Engineering'`).
    *   **Custom Attributes:** For any other field, use `JSON_EXTRACT(custom_attributes, '$.fieldName')`.
*   **Operator Choice:**
    *   Use `LIKE '%value%'` for free-text searches on names, labels, and descriptions (e.g., user name, app label, group name).
    *   Use `IN ('val1', 'val2')` when the user provides a list of exact values.
    *   Use `=` for exact matches on IDs, emails, logins, and status codes.
*   **Field Name Mapping:**
    *   `userType` -> `user_type` (column)
    *   `employeeNumber` -> `employee_number` (column)
    *   `department` -> `department` (column)
    *   `application` or `app name` -> `application.label` (column for searching)

**Step 3: JOIN & Performance Strategy**
*   **Keep JOINs Simple:** Join tables ONLY on their `okta_id` relationships (e.g., `ON u.okta_id = uf.user_okta_id`).
*   **Filter in `WHERE`:** Do NOT add filtering conditions like `status` or `factor_type` into the `ON` clause. Use the `WHERE` clause for all filtering.
*   **Prefer `NOT IN` for Exclusions:** To find records that do NOT have an associated record in another table, use the `okta_id NOT IN (SELECT ...)` subquery pattern. Avoid `LEFT JOIN ... WHERE id IS NULL`.

### 4. ADVANCED QUERY PATTERNS

**Pattern 1: API Context Integration**
*   **Context, Not a Column:** API data provided in the user prompt is context text, NOT a database column.
*   **Action:** Manually extract the IDs (`00u...`, `00g...`, `0oa...`) from the provided text. Hardcode these IDs into your query using a `WHERE okta_id IN ('id1', 'id2', ...)` clause.
*   **Example:** If context is `{"actor": {"id": "00uropbgtlUuob0uH697"}}`, your query should contain `WHERE u.okta_id = '00uropbgtlUuob0uH697'`.

**Pattern 2: Manager & Report Hierarchy**
*   **Find a User's Manager:** `SELECT m.* FROM users u JOIN users m ON u.manager = m.login WHERE u.email = 'user_email'`.
*   **Find a Manager's Reports:** `SELECT u.* FROM users u WHERE u.manager = 'manager_login'`.

**Pattern 3: Comprehensive Application Assignments (CRITICAL)**
*   When asked for user applications, user apps, application assignments, or app assignments, you MUST check for **both direct and group-based** assignments using a `UNION`.
*   Use the following template:
    ```sql
    -- Group-based assignments
    SELECT u.email, u.login, u.first_name, u.last_name, u.okta_id, a.label, a.okta_id AS application_okta_id, 'Group' AS assignment_type, g.name AS assignment_source
    FROM users u
    JOIN user_group_memberships ugm ON u.okta_id = ugm.user_okta_id
    JOIN groups g ON ugm.group_okta_id = g.okta_id
    JOIN group_application_assignments gaa ON g.okta_id = gaa.group_okta_id
    JOIN applications a ON gaa.application_okta_id = a.okta_id
    WHERE u.okta_id IN ('user_id_1', 'user_id_2') AND u.status = 'ACTIVE' AND a.status = 'ACTIVE'
    UNION
    -- Direct assignments
    SELECT u.email, u.login, u.first_name, u.last_name, u.okta_id, a.label, a.okta_id AS application_okta_id, 'Direct' AS assignment_type, 'Direct Assignment' AS assignment_source
    FROM users u
    JOIN user_application_assignments uaa ON u.okta_id = uaa.user_okta_id
    JOIN applications a ON uaa.application_okta_id = a.okta_id
    WHERE u.okta_id IN ('user_id_1', 'user_id_2') AND u.status = 'ACTIVE' AND a.status = 'ACTIVE'
    ORDER BY email, label
    ```

**Pattern 4: Timestamp Handling**
*   If a user asks for a timestamp field, you MUST format it for local time.
*   **Format:** `strftime('%Y-%m-%d %H:%M:%S', datetime(column_name, 'localtime')) AS column_name`
*   **Example:** `SELECT strftime('%Y-%m-%d %H:%M:%S', datetime(created_at, 'localtime')) AS created_at FROM users`


##### DATABASE SCHEMA (Source of Truth) #####
# CRITICAL: Always reference this schema to determine if a field is a standard column or a custom attribute.
# NEVER use JSON_EXTRACT for standard columns like user_type, department, title, organization, or manager.
# You MUST call the okta_database_schema tool to access the full database schema when needed.
        """
)

@sql_agent.system_prompt
async def okta_database_schema(ctx: RunContext[SQLDependencies]) -> str:
    """Access the complete okta database schema to answer user questions"""

    # Get custom attributes dynamically
    try:
        from src.config.settings import settings
        custom_attrs = settings.okta_user_custom_attributes_list
    except (ImportError, AttributeError):
        custom_attrs = []

    # Build custom attributes schema section
    custom_attrs_schema = ""
    if custom_attrs:
        # Simply list the available attributes. The main prompt handles the usage strategy.
        custom_attrs_schema = "\n            - custom_attributes (JSON) Contains custom attributes."
        custom_attrs_schema += "\n              Available attributes are: " + ", ".join(custom_attrs)
    else:
        custom_attrs_schema = "\n            - custom_attributes (JSON)  No custom attributes configured"


    # Build the schema string
    schema = """
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
            - status_changed_at (DateTime, INDEX)
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)""" + custom_attrs_schema + """

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
            - devices: many-to-many -> devices (via user_devices)

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

            TABLE: devices
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - status (String, INDEX)  # ACTIVE, INACTIVE, etc.
            - display_name (String, INDEX)  # Device display name
            - platform (String, INDEX)  # ANDROID, iOS, WINDOWS, etc.
            - manufacturer (String, INDEX)  # samsung, AZW, Apple, etc.
            - model (String)  # Device model
            - os_version (String)  # Operating system version
            - serial_number (String, INDEX)  # Device serial number
            - udid (String, INDEX)  # Unique device identifier
            - registered (Boolean)  # Device registration status
            - secure_hardware_present (Boolean)  # TPM/secure hardware availability
            - disk_encryption_type (String)  # USER, NONE, etc.
            - created_at (DateTime)      # From Okta 'created' field
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
            - updated_at (DateTime)      # Local record update time
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)

            INDEXES:
            - idx_device_tenant_name (tenant_id, display_name)
            - idx_device_platform (tenant_id, platform)
            - idx_device_manufacturer (tenant_id, manufacturer)
            - idx_device_serial (tenant_id, serial_number)
            - idx_device_udid (tenant_id, udid)

            UNIQUE:
            - uix_tenant_okta_id (tenant_id, okta_id)

            RELATIONSHIPS:
            - users: many-to-many -> users (via user_devices)

            TABLE: user_devices
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - user_okta_id (String, ForeignKey -> users.okta_id)
            - device_okta_id (String, ForeignKey -> devices.okta_id)
            - management_status (String)  # NOT_MANAGED, MANAGED, etc.
            - screen_lock_type (String)  # BIOMETRIC, PIN, PASSWORD, etc.
            - user_device_created_at (DateTime)  # When user was associated with device
            - created_at (DateTime)
            - last_updated_at (DateTime)
            - updated_at (DateTime)
            - last_synced_at (DateTime, INDEX)
            - is_deleted (Boolean, INDEX)

            INDEXES:
            - idx_user_device_user (tenant_id, user_okta_id)
            - idx_user_device_device (tenant_id, device_okta_id)
            - idx_user_device_mgmt_status (tenant_id, management_status)
            - idx_user_device_screen_lock (tenant_id, screen_lock_type)

            UNIQUE:
            - uix_user_device_tenant_user_device (tenant_id, user_okta_id, device_okta_id)

            RELATIONSHIPS:
            - user: many-to-one -> users
            - device: many-to-one -> devices

            TABLE: user_factors
            FIELDS:
            - id (Integer, PrimaryKey)
            - tenant_id (String, INDEX)
            - okta_id (String, INDEX)
            - user_okta_id (String, ForeignKey -> users.okta_id)
            - factor_type (String, INDEX)  ## Values can be only sms, email, signed_nonce(fastpass), password, webauthn(FIDO2), security_question, token, push(okta verify), totp
            - provider (String, INDEX)
            - status (String, INDEX)
            - authenticator_name (String, INDEX)  # Human-readable authenticator name like "Google Authenticator", "Okta Verify"
            - email (String, NULL)
            - phone_number (String, NULL)
            - device_type (String, NULL)
            - device_name (String, NULL)
            - platform (String, NULL)
            - created_at (DateTime)
            - last_updated_at (DateTime) # From Okta 'lastUpdated' field
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
            - idx_factor_auth_name (tenant_id, authenticator_name)

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
    return schema

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

def is_safe_sql(sql_query: str) -> bool:
    """Simple SQL safety check - no validation retries here, just basic safety"""
    
    if not sql_query or not isinstance(sql_query, str):
        return False
        
    sql_lower = sql_query.lower().strip()
    
    # Must have SELECT
    if not sql_lower.startswith('select'):
        return False
        
    # Block dangerous operations
    dangerous_keywords = [
        'drop', 'delete', 'insert', 'update', 'create', 'alter', 
        'truncate', 'replace', 'exec', 'execute', 'call', 'procedure'
    ]
    
    for keyword in dangerous_keywords:
        if f' {keyword} ' in f' {sql_lower} ':
            return False
            
    return True

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
