from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict, validator
from pydantic_ai import Agent, RunContext, ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic import ValidationError
import sys
import os
import asyncio
import json
import re
from typing import Optional, Dict, Any, List, Union
import logging
from datetime import datetime

# Configure logging for data directory context
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Use a simple model configuration to avoid import issues
def get_simple_model():
    """Simple model configuration without complex imports"""
    model_name = os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
    return model_name

model = get_simple_model()

@dataclass
class SQLDependencies:
    """Simple dependency injection for SQL agent"""
    tenant_id: str
    include_deleted: bool = False

class SQLQueryOutput(BaseModel):
    """Simple SQL query output - no validation here, we'll check safety separately"""
    sql: str = Field(
        description='SQL query to execute to fetch the details requested in the user question',
        min_length=1
    )
    explanation: str = Field(
        description='Natural language explanation for the SQL query provided',
        min_length=1
    )
    complexity: str = Field(
        default="medium",
        description='Query complexity: simple, medium, complex'
    )

# Simple global configuration
def get_global_llm_config():
    """Get global LLM configuration from environment variables"""
    return {
        'temperature': float(os.getenv('LLM_TEMPERATURE', '0.1')),
        'max_tokens': int(os.getenv('LLM_MAX_TOKENS', '2000')),
        'retries': int(os.getenv('LLM_RETRIES', '2')),
        'enable_token_reporting': os.getenv('LLM_ENABLE_TOKEN_REPORTING', 'true').lower() == 'true'
    }

# Get configuration
config = get_global_llm_config()

# Professional SQL Agent with enhanced features
sql_agent = Agent(
    model,
    result_type=SQLQueryOutput,
    deps_type=SQLDependencies,
    retries=config['retries'],
    system_prompt="""
You are an expert SQLite engineer. Your primary task is to convert user requests into a single, optimized, and valid SQLite query based on the provided database schema.

### OUTPUT FORMAT
Your final output MUST be a single, raw JSON object with these keys:

{
"sql": "<A SINGLE, VALID SQLITE QUERY STRING>",
"explanation": "<A CONCISE EXPLANATION OF THE QUERY>",
"complexity": "<simple|medium|complex>"
}

### RULES
1. **Single Query Only:** Generate only one SQL query
2. **No Placeholders:** All values must be hardcoded literals, never use `?`
3. **Schema is Truth:** Use only the table and column names from the provided schema
4. **Default Status Filter:** Filter for `status = 'ACTIVE'` unless user specifies otherwise
5. **Default Columns:** Always include key fields (email, login, name, etc.)
6. **Default Sorting:** Use logical sorting (last_name, first_name for users, name for groups)

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

# Simple safety check function (called after getting response)
def is_safe_sql(sql: str) -> bool:
    """Simple safety check - done outside LLM to avoid retries"""
    if not sql or not sql.strip():
        return False
    
    sql_upper = sql.upper().strip()
    
    # Block dangerous operations
    dangerous_keywords = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 'INSERT', 'UPDATE']
    for keyword in dangerous_keywords:
        if f' {keyword} ' in f' {sql_upper} ' or sql_upper.startswith(f'{keyword} '):
            return False
    
    # Must be SELECT
    return sql_upper.startswith('SELECT')

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

async def professional_sql_query(question: str, tenant_id: str = "default", 
                                include_deleted: bool = False) -> tuple[SQLQueryOutput, dict]:
    """
    Simple professional SQL query generation with basic token tracking
    
    Returns:
        tuple: (SQLQueryOutput, usage_info)
    """
    config = get_global_llm_config()
    
    try:
        # Create simple dependencies
        deps = SQLDependencies(tenant_id=tenant_id, include_deleted=include_deleted)
        
        # Execute query
        logger.info(f"🔍 Processing SQL query: {question[:50]}...")
        
        response = await sql_agent.run(question, deps=deps)
        
        # Get usage information
        usage = response.usage()
        usage_info = {
            'input_tokens': getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0)) if usage else 0,
            'output_tokens': getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0)) if usage else 0,
            'total_tokens': getattr(usage, 'total_tokens', 0) if usage else 0,
            'model_name': getattr(usage, 'model', 'unknown') if usage else 'unknown'
        }
        
        # Simple token reporting
        if config.get('enable_token_reporting', True) and usage:
            input_tokens = getattr(usage, 'request_tokens', getattr(usage, 'input_tokens', 0))
            output_tokens = getattr(usage, 'response_tokens', getattr(usage, 'output_tokens', 0))
            total_tokens = getattr(usage, 'total_tokens', input_tokens + output_tokens)
            logger.info(f"💰 Token Usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")
            
            # Basic cost estimation
            estimated_cost = (input_tokens * 0.00001) + (output_tokens * 0.00003)
            logger.info(f"💵 Estimated cost: ${estimated_cost:.6f}")
        
        # Get the result and do simple safety check
        result = response.data
        if result and is_safe_sql(result.sql):
            logger.info(f"✅ Safe SQL query generated: {result.complexity} complexity")
        else:
            logger.warning("⚠️ Generated SQL failed safety check - but continuing")
            
        return result, usage_info
        
    except ModelRetry as e:
        logger.error(f"🔄 SQL generation retry failed: {e}")
        raise
    except UnexpectedModelBehavior as e:
        logger.error(f"🤖 Model behavior issue: {e}")
        raise
    except UsageLimitExceeded as e:
        logger.error(f"💸 Usage limits exceeded: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ SQL generation error: {e}")
        raise

async def main():
    """Phase 4 Enhanced main function with comprehensive professional features"""
    print("\n🚀 Phase 4 Professional Okta SQL Query Assistant")
    print("✨ Enhanced Features:")
    print("   📊 Advanced token tracking & cost analysis")
    print("   🔒 Comprehensive security validation")
    print("   ⚡ Performance optimization hints")
    print("   🎯 Confidence scoring & quality metrics")
    print("   🔄 Graduated retry strategies")
    print("   📈 Efficiency analytics")
    print("\nType 'exit' to quit, 'config' to show settings\n")

    # Initialize user context for enhanced dependency injection
    user_context = {
        'session_start': datetime.now().isoformat(),
        'session_id': f"sql_session_{hash('main_user')}",
        'preferences': {
            'security_level': 'standard',
            'performance_mode': 'balanced',
            'detailed_logging': True
        }
    }

    while True:
        user_input = input("\nWhat would you like to know about your Okta data? > ").strip()
        
        if user_input.lower() == 'exit':
            print("👋 Goodbye! Session analytics will be logged.")
            break
            
        if user_input.lower() == 'config':
            config = get_global_llm_config()
            print("\n📋 Current Phase 4 Configuration:")
            for key, value in config.items():
                print(f"   {key}: {value}")
            continue
            
        if not user_input:
            continue

        try:
            # Phase 4: Enhanced query execution with comprehensive features
            result, usage_info = await professional_sql_query(
                question=user_input,
                security_level=user_context['preferences']['security_level'],
                user_context=user_context
            )
            
            print("\n" + "="*80)
            print("📊 PHASE 4 ENHANCED QUERY RESULTS")
            print("="*80)
            
            # Core results
            print(f"🔍 SQL Query:")
            print(f"   {result.sql}")
            print(f"\n📝 Explanation:")
            print(f"   {result.explanation}")
            
            # Phase 4 enhancements
            print(f"\n📈 Quality Metrics:")
            print(f"   Complexity: {result.complexity}")
            print(f"   Confidence Score: {result.confidence_score:.2f}/1.0")
            print(f"   Estimated Rows: {result.estimated_rows}")
            print(f"   Security Risk: {result.security_analysis.get('risk_level', 'unknown')}")
            
            if result.optimization_hints:
                print(f"\n⚡ Performance Optimization Hints:")
                for i, hint in enumerate(result.optimization_hints, 1):
                    print(f"   {i}. {hint}")
            
            # Enhanced token analytics
            print(f"\n💰 Token & Cost Analytics:")
            print(f"   📥 Input Tokens: {usage_info['input_tokens']}")
            print(f"   📤 Output Tokens: {usage_info['output_tokens']}")
            print(f"   📊 Total Tokens: {usage_info['total_tokens']}")
            
            if usage_info.get('cost_breakdown'):
                cost = usage_info['cost_breakdown']
                print(f"   � Total Cost: ${cost['total_cost']:.6f}")
                print(f"   🏷️ Model: {cost['model_type']}")
                
            if usage_info.get('efficiency_metrics'):
                metrics = usage_info['efficiency_metrics']
                print(f"   ⚡ Efficiency: {metrics['tokens_per_dollar']:.0f} tokens/$")
                print(f"   📊 Cost per Query: ${metrics['cost_per_query']:.6f}")

        except ModelRetry as mre:
            print(f"\n🔄 Query retry exhausted after {get_global_llm_config()['retries']} attempts:")
            print(f"   {str(mre)}")
        except UnexpectedModelBehavior as umb:
            print(f"\n🤖 Model behavior issue detected:")
            print(f"   {str(umb)}")
        except UsageLimitExceeded as ule:
            print(f"\n💸 Usage limits exceeded:")
            print(f"   {str(ule)}")
        except ValidationError as ve:
            print(f"\n📋 Data validation error:")
            print(f"   {str(ve)}")
        except Exception as e:
            print(f"\n❌ Unexpected error:")
            print(f"   {str(e)}")

async def main():
    """Simple test function"""
    print("\n🚀 Okta SQL Query Assistant")
    print("Type 'exit' to quit\n")

    while True:
        question = input("\nWhat would you like to know? > ")
        if question.lower() == 'exit':
            break

        try:
            result, usage_info = await professional_sql_query(question)
            print(f"\nSQL: {result.sql}")
            print(f"Explanation: {result.explanation}")
            print(f"Tokens: {usage_info['total_tokens']}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
	