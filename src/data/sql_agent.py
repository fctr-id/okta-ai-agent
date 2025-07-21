from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior, UsageLimitExceeded
from dotenv import load_dotenv
import asyncio
import os
import json
import re

load_dotenv()

# Use the model picker approach from the working version
try:
    from src.core.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
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
    retries=0,  # Keep simple - no retries to avoid validation issues
    system_prompt="""You are an expert-level SQLite engineer. Your primary task is to convert user requests into a single, optimized, and valid SQLite query based on the provided database schema. You must follow all rules and patterns outlined below without deviation.

### 1. CORE DIRECTIVE: OUTPUT FORMAT
Your final output MUST be a single, raw JSON object. It must contain two keys: `sql` and `explanation`. Do not add any extra characters, newlines, or text outside of this JSON structure.
{
"sql": "<A SINGLE, VALID SQLITE QUERY STRING>",
"explanation": "<A CONCISE EXPLANATION OF THE QUERY. If the user asks to save or download, begin the explanation with 'SAVE_FILE'.>"
}

### 2. GOLDEN RULES (APPLY TO ALL QUERIES)
1.  **Single Query Only:** You MUST generate only one SQL query. Do not use placeholders (`?`).
2.  **Schema is Truth:** The database schema provided is the ONLY source of truth. NEVER use columns not explicitly listed.
3.  **Default Filters:** Unless specified otherwise, you MUST filter for `status = 'ACTIVE'` for users and applications.
4.  **Default Columns & Sorting:**
    *   **Users:** ALWAYS include `email`, `login`, `first_name`, `last_name`, `status`. Include `okta_id` for queries involving relationships. Sort by `last_name`, `first_name`.
    *   **Groups:** ALWAYS include `name`, `description`, `okta_id`. Sort by `name`.
    *   **Applications:** ALWAYS include `label`, `name`, `status`, `okta_id`. Sort by `label`.
5.  **Operator Choice:** Use `LIKE '%value%'` for free-text searches (names, labels), `IN ('val1', 'val2')` for lists, and `=` for exact matches (IDs, emails, status).
6.  **Custom Attributes:** For fields not in the standard schema, use `JSON_EXTRACT(custom_attributes, '$.fieldName')`.
7.  **JOINs:** Join tables ONLY on their `okta_id` relationships (e.g., `ON u.okta_id = ugm.user_okta_id`).

### 3. QUERY PATTERNS

**Pattern 1: User Groups & Applications (Most Important)**
*   To get a complete view of a user's groups and all applications (both direct and group-based), you MUST use the following `UNION` pattern. This ensures all groups are listed, even if they have no associated apps.

    ```sql
    -- Get all groups and any group-based apps
    SELECT u.email, u.first_name, u.last_name, g.name as group_name, a.label as application_label, 'Group' as assignment_type, g.name as assignment_source
    FROM users u
    LEFT JOIN user_group_memberships ugm ON u.okta_id = ugm.user_okta_id
    LEFT JOIN groups g ON ugm.group_okta_id = g.okta_id
    LEFT JOIN group_application_assignments gaa ON g.okta_id = gaa.group_okta_id
    LEFT JOIN applications a ON gaa.application_okta_id = a.okta_id AND a.status = 'ACTIVE'
    WHERE u.okta_id IN ('user_id_1', 'user_id_2') AND u.status = 'ACTIVE'
    UNION
    -- Get all direct app assignments
    SELECT u.email, u.first_name, u.last_name, NULL as group_name, a.label as application_label, 'Direct' as assignment_type, 'Direct Assignment' as assignment_source
    FROM users u
    JOIN user_application_assignments uaa ON u.okta_id = uaa.user_okta_id
    JOIN applications a ON uaa.application_okta_id = a.okta_id
    WHERE u.okta_id IN ('user_id_1', 'user_id_2') AND u.status = 'ACTIVE' AND a.status = 'ACTIVE'
    ORDER BY email, group_name, application_label
    ```

**Pattern 2: API Context Integration**
*   If the prompt contains context with IDs (e.g., from a previous API call), you MUST extract those IDs and hardcode them into your query using a `WHERE okta_id IN ('id1', 'id2', ...)` clause.

**Pattern 3: Manager & Report Hierarchy**
*   **Find a User's Manager:** `SELECT m.* FROM users u JOIN users m ON u.manager = m.login WHERE u.email = 'user_email'`.
*   **Find a Manager's Reports:** `SELECT u.* FROM users u WHERE u.manager = 'manager_login'`.

**Pattern 4: Timestamp Handling**
*   If a user asks for a timestamp, format it for local time: `strftime('%Y-%m-%d %H:%M:%S', datetime(column_name, 'localtime')) AS column_name`.

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
    
    # Remove comments completely for analysis
    lines = sql_lower.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('--'):
            # Remove inline comments
            if '--' in line:
                line = line.split('--')[0].strip()
            if line:
                cleaned_lines.append(line)
    
    if not cleaned_lines:
        return False
        
    cleaned_sql = ' '.join(cleaned_lines)
    
    # Must be a SELECT statement (can start with WITH for CTEs)
    if not (cleaned_sql.startswith('select') or cleaned_sql.startswith('with')):
        return False
    
    # Block truly dangerous operations (but allow CTEs and complex queries)
    dangerous_patterns = [
        'drop table', 'drop database', 'drop schema', 'drop view',
        'delete from', 'insert into', 'update set',
        'truncate table', 'create table', 'alter table',
        'exec ', 'execute ', 'call ', 'procedure ',
        '; drop', '; delete', '; insert', '; update', '; create'
    ]
    
    for pattern in dangerous_patterns:
        if pattern in cleaned_sql:
            return False
    
    # Additional safety: ensure it's primarily a read operation
    # Allow WITH clauses, subqueries, JOINs, UNIONs - all safe for read operations
    if 'select' not in cleaned_sql:
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
            # Use structured output directly (no manual JSON parsing needed)
            deps = SQLDependencies(tenant_id="default", include_deleted=False)
            result = await sql_agent.run(question, deps=deps)
            
            # Simple token usage reporting (keeping it minimal)
            if hasattr(result, 'usage') and result.usage():
                usage = result.usage()
                input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
                output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
                print(f"💰 Token Usage: {input_tokens} in, {output_tokens} out")

            print("\nGenerated SQL:")
            print("-" * 40)
            print(result.output.sql)
            print("\nExplanation:")
            print(result.output.explanation)

        except ModelRetry as e:
            print(f"\n🔄 Retry needed: {e}")
        except UnexpectedModelBehavior as e:
            print(f"\n⚠️ Unexpected behavior: {e}")
        except UsageLimitExceeded as e:
            print(f"\n💰 Usage limit exceeded: {e}")
        except Exception as e:
            print(f"\nError: {str(e)}")

        print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())
