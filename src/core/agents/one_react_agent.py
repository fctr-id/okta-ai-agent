"""
ReAct Agent for Okta Query Execution
Single agent with 7 tools for reasoning and acting on hybrid SQLite + API queries

This agent follows the ReAct (Reasoning + Acting) pattern:
1. Reason about what data is needed
2. Act by calling tools to gather information
3. Observe results and decide next steps
4. Repeat until query is answered or max retries exceeded
"""

from pydantic_ai import Agent, RunContext, FunctionToolset
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass
import logging
import json
import os
import time
from pathlib import Path

from src.utils.logging import get_logger, set_correlation_id, get_default_log_dir

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    model = ModelConfig.get_model(ModelType.CODING)
except ImportError:
    # Fallback to simple model configuration
    logger.warning("Could not import model_picker, using fallback model configuration")
    model = os.getenv('LLM_MODEL', 'openai:gpt-4o-mini')

# ============================================================================
# Lightweight JSON Generation for One React Agent
# ============================================================================

def generate_lightweight_onereact_json(force_regenerate: bool = False) -> Dict[str, Any]:
    """
    Generate a minimal lightweight JSON structure for one_react_agent.
    Uses simple dot notation: entity.operation (e.g., "application.list")
    
    This structure is optimized for small LLMs:
    - Flat array of strings with dot notation
    - No nested objects to parse
    - Minimal token count
    - Easy to filter by splitting on '.'
    
    Args:
        force_regenerate: If True, regenerate even if file exists
        
    Returns:
        Dict with 'operations' (list of strings) and 'sql_tables' (list of strings)
    """
    schemas_dir = Path("src/data/schemas")
    lightweight_path = schemas_dir / "lightweight_onereact.json"
    source_path = schemas_dir / "Okta_API_entitity_endpoint_reference_GET_ONLY.json"
    
    # Load existing file if it exists and regeneration not forced
    if lightweight_path.exists() and not force_regenerate:
        logger.info(f"Loading existing lightweight_onereact.json from {lightweight_path}")
        try:
            with open(lightweight_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load existing file: {e}. Regenerating...")
    
    # Generate new lightweight structure
    logger.info("Generating new lightweight_onereact.json...")
    
    # Load source endpoint data
    if not source_path.exists():
        logger.error(f"Source file not found: {source_path}")
        return {"operations": [], "sql_tables": []}
    
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            source_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load source file: {e}")
        return {"operations": [], "sql_tables": []}
    
    # Extract operations in dot notation format
    operations = []
    seen_operations = set()  # Deduplicate
    
    endpoints = source_data.get('endpoints', [])
    for endpoint in endpoints:
        entity = endpoint.get('entity', '')
        operation = endpoint.get('operation', '')
        
        if entity and operation:
            # Create dot notation: entity.operation
            op_string = f"{entity}.{operation}"
            if op_string not in seen_operations:
                operations.append(op_string)
                seen_operations.add(op_string)
    
    # Sort for consistency
    operations.sort()
    
    # SQL tables (from SQLite schema)
    sql_tables = [
        "applications",
        "users",
        "groups",
        "group_memberships",
        "application_users",
        "application_groups",
        "roles",
        "user_roles"
    ]
    
    # Create minimal structure
    lightweight_data = {
        "operations": operations,
        "sql_tables": sql_tables
    }
    
    # Save to file
    try:
        schemas_dir.mkdir(parents=True, exist_ok=True)
        with open(lightweight_path, 'w', encoding='utf-8') as f:
            json.dump(lightweight_data, f, indent=2)
        logger.info(f"Generated lightweight_onereact.json with {len(operations)} operations")
    except Exception as e:
        logger.error(f"Failed to save lightweight_onereact.json: {e}")
    
    return lightweight_data

# ============================================================================
# Schema Helper Function
# ============================================================================

def get_sqlite_schema_description() -> str:
    """
    Generate a comprehensive LLM-optimized description of the SQLite database schema.
    Adapted from sql_generation_agent with enhanced details.
    
    Returns:
        Formatted schema description string with complete table details
    """
    # Get custom attributes dynamically
    try:
        from config.settings import settings
        custom_attrs = settings.okta_user_custom_attributes_list
    except (ImportError, AttributeError):
        custom_attrs = []

    # Build custom attributes schema section
    custom_attrs_schema = ""
    if custom_attrs:
        custom_attrs_schema = "\n            - custom_attributes (JSON) Contains custom attributes."
        custom_attrs_schema += "\n              Available attributes are: " + ", ".join(custom_attrs)
    else:
        custom_attrs_schema = "\n            - custom_attributes (JSON)  No custom attributes configured"

    # Build the comprehensive schema
    schema = """
=========================================================================================================
COMPLETE SQLITE DATABASE SCHEMA
=========================================================================================================

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

---------------------------------------------------------------------------------------------------------

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

=========================================================================================================
IMPORTANT QUERY GUIDELINES
=========================================================================================================

1. DEFAULT FILTERS:
   - Always filter by status = 'ACTIVE' unless user specifies otherwise
   - Filter by is_deleted = 0 or NULL for active records
   - Use tenant_id when available for multi-tenant environments

2. RELATIONSHIPS:
   - Join tables using okta_id fields (e.g., users.okta_id = user_factors.user_okta_id)
   - For user applications: Check BOTH direct assignments AND group-based assignments (UNION pattern)

3. PERFORMANCE:
   - Use indexed fields in WHERE clauses for better performance
   - Leverage composite indexes when filtering by multiple fields
   - Use LIMIT for test queries (LIMIT 3 for testing)

4. COMMON PATTERNS:
   - User's groups: JOIN user_group_memberships ON users.okta_id = user_group_memberships.user_okta_id
   - User's apps: UNION of user_application_assignments (direct) + group_application_assignments (via groups)
   - User's MFA: JOIN user_factors ON users.okta_id = user_factors.user_okta_id

=========================================================================================================
"""
    return schema

# ============================================================================
# Dependencies (Dataclass for PydanticAI)
# ============================================================================

@dataclass
class ReactAgentDependencies:
    """Dependencies injected into ReAct agent"""
    correlation_id: str
    endpoints: List[Dict[str, Any]]  # Full endpoint details (for Tool 3)
    lightweight_entities: Dict[str, Any]  # Lightweight entity-operation mapping (for Tool 2)
    okta_client: Any  # OktaClient instance
    sqlite_connection: Any  # SQLite connection
    operation_mapping: Dict[str, Any]
    user_query: str  # Original user query for context
    progress_callback: Optional[Any] = None  # Optional callback for progress updates
    
    # NEW: SSE streaming callbacks for real-time UI updates
    step_start_callback: Optional[callable] = None  # Called when a discovery step starts
    step_end_callback: Optional[callable] = None    # Called when a discovery step completes
    step_tokens_callback: Optional[callable] = None # Called to report token usage per step
    tool_call_callback: Optional[callable] = None   # Called when a tool is invoked
    
    # Circuit breaker counters for tool execution limits
    sql_execution_count: int = 0
    api_execution_count: int = 0
    schema_load_count: int = 0
    endpoint_filter_count: int = 0
    
    # Circuit breaker limits (configurable via environment variables)
    MAX_SQL_EXECUTIONS: int = int(os.getenv('REACT_AGENT_MAX_SQL_EXECUTIONS', '5'))
    MAX_API_EXECUTIONS: int = int(os.getenv('REACT_AGENT_MAX_API_EXECUTIONS', '20'))
    MAX_SCHEMA_LOADS: int = int(os.getenv('REACT_AGENT_MAX_SCHEMA_LOADS', '3'))
    MAX_ENDPOINT_FILTERS: int = int(os.getenv('REACT_AGENT_MAX_ENDPOINT_FILTERS', '10'))

# ============================================================================
# Structured Outputs
# ============================================================================

class ExecutionResult(BaseModel):
    """Final execution result from ReAct agent"""
    success: bool
    results: Optional[Any] = None
    execution_plan: str
    steps_taken: List[str]
    error: Optional[str] = None
    complete_production_code: str = ""  # REQUIRED: The final, complete, runnable Python script to reproduce results

# ============================================================================
# Tool Implementations
# ============================================================================

def create_react_toolset(deps: ReactAgentDependencies) -> FunctionToolset:
    """Create function toolset with all 7 tools for the ReAct agent"""
    
    toolset = FunctionToolset()
    
    # Helper to notify frontend of tool calls
    async def notify_tool_call(tool_name: str, tool_description: str):
        """Send tool call notification via SSE callback"""
        if hasattr(deps, 'tool_call_callback') and deps.tool_call_callback:
            await deps.tool_call_callback({
                "tool_name": tool_name,
                "description": tool_description,
                "timestamp": time.time()
            })
    
    # ========================================================================
    # Tool 1: Load SQLite Schema
    # ========================================================================
    
    async def load_sql_schema(ctx: RunContext[ReactAgentDependencies]) -> Dict[str, Any]:
        """
        Load SQLite database schema to understand what data is available in the database.
        Call this FIRST to see what tables, columns, and relationships exist.
        
        Returns:
            Complete schema description with tables, columns, indexes, and relationships
        """
        # Notify frontend
        await notify_tool_call("load_sql_schema", "Loading database schema")
        
        # Circuit breaker check
        if deps.schema_load_count >= deps.MAX_SCHEMA_LOADS:
            logger.warning(f"[{deps.correlation_id}] Schema load circuit breaker triggered: {deps.schema_load_count}/{deps.MAX_SCHEMA_LOADS}")
            return {
                "status": "error",
                "schema": "",
                "error": f"⚠️ CIRCUIT BREAKER: Schema loaded {deps.schema_load_count} times (max: {deps.MAX_SCHEMA_LOADS}). You MUST call stop_execution() tool now with reason='Schema load limit exceeded' and a clear user message explaining the query couldn't be completed due to repeated schema loads."
            }
        
        deps.schema_load_count += 1
        logger.info(f"[{deps.correlation_id}] Tool 1: Loading SQLite schema on-demand (load #{deps.schema_load_count}/{deps.MAX_SCHEMA_LOADS})")
        
        try:
            # Generate the full schema description
            schema_text = get_sqlite_schema_description()
            
            return {
                "status": "success",
                "schema": schema_text,
                "note": "Use this schema to understand what data is available in the database and write SQL queries"
            }
        except Exception as e:
            logger.error(f"[{deps.correlation_id}] Failed to load schema: {e}", exc_info=True)
            return {
                "status": "error",
                "schema": "",
                "error": str(e)
            }
    
    # ========================================================================
    # Tool 2: Load Comprehensive API Endpoints
    # ========================================================================
    
    async def load_comprehensive_api_endpoints(ctx: RunContext[ReactAgentDependencies]) -> Dict[str, Any]:
        """
        Load lightweight summary of all API entities and operations.
        Returns operations in simple dot notation (e.g., "application.list", "user.get").
        
        Returns:
            Dictionary with operations list (in entity.operation format)
        """
        await notify_tool_call("load_comprehensive_api_endpoints", "Loading API endpoints catalog")
        logger.info(f"[{deps.correlation_id}] Tool 2: Loading comprehensive API endpoints (lightweight)")
        
        # Handle both old format (entity-grouped dict) and new format (operations list)
        if isinstance(deps.lightweight_entities, dict):
            # Check if it's the new format with "operations" key
            if 'operations' in deps.lightweight_entities:
                # New minimal format: {"operations": ["entity.operation", ...], "sql_tables": [...]}
                operations = deps.lightweight_entities.get('operations', [])
                
                # Group by entity for easier browsing
                entities_grouped = {}
                for op in operations:
                    if '.' in op:
                        entity, operation = op.split('.', 1)
                        if entity not in entities_grouped:
                            entities_grouped[entity] = []
                        entities_grouped[entity].append(operation)
                
                result = {
                    "operations": operations,  # Full list in dot notation
                    "entities": entities_grouped,  # Grouped by entity for easier browsing
                    "total_entities": len(entities_grouped),
                    "total_operations": len(operations),
                    "format": "dot_notation"
                }
            else:
                # Old format: {"entity_name": {"operations": [...], "methods": [...]}}
                result_entities = {}
                for entity_name, entity_data in deps.lightweight_entities.items():
                    result_entities[entity_name] = {
                        'operations': entity_data.get('operations', []),
                        'methods': entity_data.get('methods', ['GET']),
                        'operation_count': len(entity_data.get('operations', []))
                    }
                
                result = {
                    "entities": result_entities,
                    "total_entities": len(result_entities),
                    "total_operations": sum(e['operation_count'] for e in result_entities.values()),
                    "format": "entity_grouped"
                }
        else:
            # Fallback for unexpected format
            result = {
                "entities": {},
                "total_entities": 0,
                "total_operations": 0,
                "format": "unknown",
                "error": "Unexpected lightweight_entities format"
            }
        
        logger.info(f"[{deps.correlation_id}] Loaded {result['total_entities']} entities with {result['total_operations']} operations (format: {result.get('format')})")
        
        return result
    
    # ========================================================================
    # Tool 3: Filter Endpoints by Operations
    # ========================================================================
    
    async def filter_endpoints_by_operations(
        operation_names: List[str]
    ) -> Dict[str, Any]:
        """
        Get FULL detailed endpoint information for specific operations.
        
        Args:
            operation_names: List of operation identifiers in one of these formats:
                - Dot notation: "entity.operation" (e.g., "application_credential.list_keys")
                - Plain operation: "operation" (e.g., "list_keys")
                - Old compound format: "entity_operation" (e.g., "application_credential_list_keys")
        
        Returns:
            Dictionary with full endpoint details for selected operations
        """
        await notify_tool_call("filter_endpoints_by_operations", f"Getting details for {len(operation_names)} operations")
        
        # Circuit breaker check
        if deps.endpoint_filter_count >= deps.MAX_ENDPOINT_FILTERS:
            logger.warning(f"[{deps.correlation_id}] Endpoint filter circuit breaker triggered: {deps.endpoint_filter_count}/{deps.MAX_ENDPOINT_FILTERS}")
            return {
                "endpoints": [],
                "total_endpoints_returned": 0,
                "error": f"⚠️ CIRCUIT BREAKER: Endpoint filtering called {deps.endpoint_filter_count} times (max: {deps.MAX_ENDPOINT_FILTERS}). You MUST call stop_execution() tool now with reason='Endpoint filter limit exceeded' and a clear user message explaining the query couldn't be completed."
            }
        
        deps.endpoint_filter_count += 1
        logger.info(f"[{deps.correlation_id}] Tool 3: Filtering endpoints for operations: {operation_names} (call #{deps.endpoint_filter_count}/{deps.MAX_ENDPOINT_FILTERS})")
        
        selected_endpoints = []
        
        # Parse operation_names to extract entity and operation pairs
        # Supports: "entity.operation", "operation", or "entity_operation"
        search_pairs = []
        for op_name in operation_names:
            if '.' in op_name:
                # Dot notation: "application_credential.list_keys"
                parts = op_name.split('.', 1)
                if len(parts) == 2:
                    search_pairs.append((parts[0], parts[1]))
            else:
                # Plain operation or compound format - search by operation only
                search_pairs.append((None, op_name))
        
        # Match endpoints by entity + operation
        for endpoint in deps.endpoints:
            endpoint_entity = endpoint.get('entity', '')
            endpoint_operation = endpoint.get('operation', '')
            
            # Check if this endpoint matches any search pair
            for search_entity, search_operation in search_pairs:
                if search_entity:
                    # Entity specified - must match both
                    if endpoint_entity == search_entity and endpoint_operation == search_operation:
                        # Security validation
                        from src.core.security import validate_api_endpoint
                        security_result = validate_api_endpoint(endpoint)
                        if security_result.is_valid:
                            selected_endpoints.append(endpoint)
                        else:
                            logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
                        break  # Found match, move to next endpoint
                else:
                    # No entity specified - match by operation only
                    if endpoint_operation == search_operation:
                        # Security validation
                        from src.core.security import validate_api_endpoint
                        security_result = validate_api_endpoint(endpoint)
                        if security_result.is_valid:
                            selected_endpoints.append(endpoint)
                        else:
                            logger.warning(f"Endpoint filtered for security: {endpoint.get('id', 'unknown')} - {'; '.join(security_result.violations)}")
                        break  # Found match, move to next endpoint
        
        result = {
            "endpoints": selected_endpoints,
            "total_endpoints_returned": len(selected_endpoints),
            "operations_found": [f"{ep.get('entity')}.{ep.get('operation')}" for ep in selected_endpoints]
        }
        
        logger.info(f"[{deps.correlation_id}] Found {len(selected_endpoints)} endpoints for {len(operation_names)} operation queries")
        
        return result
    
    # ========================================================================
    # Tool 4: Get DB Code Generation Prompt (NOT a code generator!)
    # ========================================================================
    
    async def get_sql_code_generation_prompt(
        query_description: str,
        limit: int = 3
    ) -> Dict[str, Any]:
        """
        Get the prompt template for generating SQL queries.
        The ReAct agent itself will generate the code using this guidance.
        
        Args:
            query_description: Natural language description of what to query
            limit: Number of records to return (default 3 for testing)
        
        Returns:
            Dictionary with code generation prompt and guidelines (schema already in system context)
        """
        await notify_tool_call("get_sql_code_generation_prompt", "Getting SQL code generation guidance")
        logger.info(f"[{deps.correlation_id}] Tool 4: Getting SQL code generation prompt")
        
        # Load SQL generation prompt from file (ReAct agent specific)
        sql_prompt_file = Path(__file__).parent / "prompts" / "sql_code_gen_react_agent_system_prompt.txt"
        try:
            with open(sql_prompt_file, 'r', encoding='utf-8') as f:
                sql_prompt = f.read()
        except FileNotFoundError:
            sql_prompt = """Generate a SQLite-compatible SQL query.
            
Rules:
- Use proper SELECT, FROM, JOIN syntax
- Always include LIMIT clause for safety
- Use proper table names from the schema in your system context
- Use proper column names from the schema in your system context
- Return only the data requested
"""
        
        # Schema is already in system prompt - don't duplicate it here
        return {
            "code_generation_prompt": sql_prompt,
            "query_task": query_description,
            "limit": limit
        }
    
    # ========================================================================
    # Tool 5: Get API Code Generation Prompt (NOT a code generator!)
    # ========================================================================
    
    async def get_api_code_generation_prompt(
        query_description: str,
        endpoints: List[str],
        max_results: int = 3
    ) -> Dict[str, Any]:
        """
        Get the prompt template for generating Python API code.
        The ReAct agent itself will generate the code using this guidance.
        
        Args:
            query_description: Natural language description of what to fetch
            endpoints: List of operation names (e.g., ["group.list", "user.get"])
            max_results: Maximum number of records to return (default 3 for testing)
        
        Returns:
            Dictionary with code generation prompt and guidelines
        """
        await notify_tool_call("get_api_code_generation_prompt", "Getting API code generation guidance")
        logger.info(f"[{deps.correlation_id}] Tool 5: Getting API code generation prompt")
        
        # Load API code generation prompt from file (ReAct agent specific)
        api_prompt_file = Path(__file__).parent / "prompts" / "api_code_gen_react_agent_system_prompt.txt"
        try:
            with open(api_prompt_file, 'r', encoding='utf-8') as f:
                api_prompt = f.read()
        except FileNotFoundError:
            api_prompt = """Generate Python code using the Okta SDK to fetch data from the API.
            
Rules:
- Use the OktaAPIClient available as deps.okta_client
- Always add max_results={max_results} to paginated calls for testing
- Use async/await for API calls
- Handle errors gracefully
- Return structured data (list of dicts)
"""
        
        return {
            "code_generation_prompt": api_prompt,
            "query_task": query_description,
            "max_results": max_results,
            "target_operations": endpoints,  # Changed from available_endpoints - now just operation names
            "okta_client_available": "YES - Variable 'client' is pre-injected (see prompt for details)"
        }
    
    # ========================================================================
    # Tool 6: Execute Test Query (executes code generated by the agent)
    # ========================================================================
    
    async def execute_test_query(
        code: str,
        code_type: Literal["sql", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Execute test query and return sample results.
        
        For python_sdk type:
        - Generate ONLY the async function with Okta API logic
        - We will wrap it with client setup and execution boilerplate
        - Use 'client' variable for OktaAPIClient calls
        - Store final data in 'results' variable
        
        Example - You generate this:
        ```python
        async def fetch_data():
            response = await client.make_request(
                endpoint="/api/v1/users",
                method="GET",
                params={"limit": 3}
            )
            return response.get('data', [])
        
        results = await fetch_data()
        ```
        
        Args:
            code: Generated code from Tool 4 or Tool 5
            code_type: Type of code to execute
        
        Returns:
            Dictionary with execution results and metadata
        """
        await notify_tool_call("execute_test_query", f"Executing {code_type} test query")
        
        # Circuit breaker checks BEFORE execution
        if code_type == "sql":
            if deps.sql_execution_count >= deps.MAX_SQL_EXECUTIONS:
                logger.warning(f"[{deps.correlation_id}] SQL circuit breaker triggered: {deps.sql_execution_count}/{deps.MAX_SQL_EXECUTIONS}")
                return {
                    "success": False,
                    "sample_results": None,
                    "total_records": 0,
                    "execution_time_ms": 0,
                    "columns": [],
                    "error": f"⚠️ CIRCUIT BREAKER: {deps.sql_execution_count} SQL queries attempted (max: {deps.MAX_SQL_EXECUTIONS}). You MUST call stop_execution() tool now with reason='SQL execution limit exceeded' and user_message='Unable to find an answer to your query after {deps.sql_execution_count} SQL attempts. The data may not be available in the database, or the query is too complex. Please try rephrasing or breaking it into smaller parts.'"
                }
            deps.sql_execution_count += 1
            logger.info(f"[{deps.correlation_id}] Tool 6: Executing SQL test query (execution #{deps.sql_execution_count}/{deps.MAX_SQL_EXECUTIONS})")
            
        elif code_type == "python_sdk":
            if deps.api_execution_count >= deps.MAX_API_EXECUTIONS:
                logger.warning(f"[{deps.correlation_id}] API circuit breaker triggered: {deps.api_execution_count}/{deps.MAX_API_EXECUTIONS}")
                return {
                    "success": False,
                    "sample_results": None,
                    "total_records": 0,
                    "execution_time_ms": 0,
                    "columns": [],
                    "error": f"⚠️ CIRCUIT BREAKER: {deps.api_execution_count} API calls attempted (max: {deps.MAX_API_EXECUTIONS}). You MUST call stop_execution() tool now with reason='API execution limit exceeded' and user_message='Unable to find an answer to your query after {deps.api_execution_count} API attempts. The required data may not be accessible via the API, or the query is too complex. Please try rephrasing or breaking it into smaller parts.'"
                }
            deps.api_execution_count += 1
            logger.info(f"[{deps.correlation_id}] Tool 6: Executing API test query (execution #{deps.api_execution_count}/{deps.MAX_API_EXECUTIONS})")
        
        # Log the generated code for debugging
        logger.debug(f"[{deps.correlation_id}] Generated code to execute:\n{code}")
        
        import time
        
        start_time = time.time()
        
        try:
            if code_type == "sql":
                # VALIDATION: Check for LIMIT 3 in SQL code
                if "LIMIT 3" not in code.upper():
                    return {
                        "success": False,
                        "sample_results": None,
                        "total_records": 0,
                        "execution_time_ms": 0,
                        "columns": [],
                        "error": "❌ VALIDATION FAILED: SQL query is missing 'LIMIT 3'. All test queries MUST include 'LIMIT 3' at the end to prevent excessive data retrieval during testing. Please add 'LIMIT 3' to your query and try again."
                    }
                
                # Execute SQL query against SQLite
                cursor = deps.sqlite_connection.cursor()
                cursor.execute(code)
                results = cursor.fetchall()
                
                # Get column names from cursor description
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                
                # Convert to list of dicts
                if results:
                    sample_results = [dict(zip(columns, row)) for row in results]
                else:
                    sample_results = []
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "sample_results": sample_results,
                    "total_records": len(sample_results),
                    "execution_time_ms": execution_time_ms,
                    "columns": columns,
                    "error": None
                }
            
            elif code_type == "python_sdk":
                # VALIDATION: Check for max_results=3 or less in Python SDK code
                # Accept max_results=1, max_results=2, or max_results=3
                import re
                max_results_pattern = r'max_results\s*=\s*([123])\b'
                if not re.search(max_results_pattern, code):
                    return {
                        "success": False,
                        "sample_results": None,
                        "total_records": 0,
                        "execution_time_ms": 0,
                        "columns": [],
                        "error": "❌ VALIDATION FAILED: API code is missing 'max_results=3' (or 1, 2). All test API calls MUST include 'max_results' with a value of 3 or less in the client.make_request() call to prevent excessive API requests during testing. Please add 'max_results=3' to your API call and try again."
                    }
                
                # Execute Python SDK code
                # We're already in an async context
                import asyncio
                
                # Create namespace with okta_client available
                namespace = {
                    'client': deps.okta_client,
                    'okta_client': deps.okta_client,
                    'asyncio': asyncio
                }
                
                # Wrap code in async function to handle await statements
                # API/SDK code - extract function name and call it
                import re
                func_match = re.search(r'async\s+def\s+(\w+)\s*\(', code)
                if not func_match:
                    return ExecutionResult(
                        success=False,
                        error_message="Generated code must define an async function starting with 'async def function_name():'",
                        execution_time=0.0,
                        complete_production_code=""
                    )
                
                func_name = func_match.group(1)
                
                # Wrap: define the function inside a wrapper, call it, and return results
                wrapped_code = f"""async def __exec_wrapper__():
{chr(10).join('    ' + line for line in code.split(chr(10)))}
    return await {func_name}()
"""
                
                # Log the wrapped code for debugging
                logger.debug(f"[{deps.correlation_id}] Wrapped code:\n{wrapped_code}")
                
                # Execute to define the wrapper function in namespace
                exec(wrapped_code, namespace)
                
                # Now await the wrapper coroutine (we're in an async context)
                results = await namespace['__exec_wrapper__']()
                
                # Convert to list if needed
                if not isinstance(results, list):
                    results = [results]
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "sample_results": results[:3],  # Limit to 3 for testing
                    "total_records": len(results),
                    "execution_time_ms": execution_time_ms,
                    "columns": list(results[0].keys()) if results and isinstance(results[0], dict) else [],
                    "error": None
                }
            
            else:
                return {
                    "success": False,
                    "sample_results": None,
                    "total_records": 0,
                    "execution_time_ms": 0,
                    "columns": [],
                    "error": f"Unknown code_type: {code_type}"
                }
        
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[{deps.correlation_id}] Test execution failed: {e}", exc_info=True)
            
            return {
                "success": False,
                "sample_results": None,
                "total_records": 0,
                "execution_time_ms": execution_time_ms,
                "columns": [],
                "error": str(e)
            }
    
    # ========================================================================
    # Tool 7: Log Progress (NEW - for user feedback)
    # ========================================================================
    
    async def log_progress(
        action: str,
        reasoning: str,
        status: Literal["starting", "completed", "thinking"] = "starting"
    ) -> Dict[str, Any]:
        """
        Log your current action and reasoning to keep users informed of progress.
        Call this before and after major steps to provide visibility into your thought process.
        
        Args:
            action: What you're doing (e.g., "Loading database schema", "Testing SQL query")
            reasoning: Why you're taking this action (e.g., "Need to understand available tables")
            status: Whether you're starting an action, completed it, or just thinking
        
        Returns:
            Acknowledgment that progress was logged
        """
        logger.info(f"[{deps.correlation_id}] 🎯 {status.upper()}: {action}")
        logger.info(f"[{deps.correlation_id}] 💭 Reasoning: {reasoning}")
        
        # If progress callback is provided, send event to frontend (legacy)
        if hasattr(deps, 'progress_callback') and deps.progress_callback:
            await deps.progress_callback({
                "type": "agent_progress",
                "action": action,
                "reasoning": reasoning,
                "status": status,
                "timestamp": time.time()
            })
        
        # NEW: SSE streaming callbacks for real-time UI
        if status == "starting" and hasattr(deps, 'step_start_callback') and deps.step_start_callback:
            await deps.step_start_callback({
                "title": action,
                "text": reasoning,
                "timestamp": time.time()
            })
        elif status == "completed" and hasattr(deps, 'step_end_callback') and deps.step_end_callback:
            await deps.step_end_callback({
                "title": action,
                "text": reasoning,
                "timestamp": time.time()
            })
        
        return {
            "logged": True,
            "message": f"Progress logged: {action}",
            "status": status
        }
    
    # ========================================================================
    # Tool 8: Generate Production Code
    # ========================================================================
    
    async def generate_production_code(
        test_code: str,
        test_results: Dict[str, Any],
        code_type: Literal["cypher", "python_sdk"]
    ) -> Dict[str, Any]:
        """
        Generate production-ready code based on validated test code.
        
        Args:
            test_code: Validated test code from Tool 4 or Tool 5
            test_results: Results from Tool 6 execution
            code_type: Type of code to generate
        
        Returns:
            Dictionary with production code and optimizations applied
        """
        logger.info(f"[{deps.correlation_id}] Tool 7: Generating production code (type: {code_type})")
        
        import re
        
        production_code = test_code
        optimizations_applied = []
        
        if code_type == "cypher":
            # Remove LIMIT clause for full dataset
            limit_pattern = r'\s+LIMIT\s+\d+\s*$'
            if re.search(limit_pattern, production_code, re.IGNORECASE):
                production_code = re.sub(limit_pattern, '', production_code, flags=re.IGNORECASE)
                optimizations_applied.append("Removed LIMIT clause for full dataset")
        
        elif code_type == "python_sdk":
            # Remove max_results parameter from API calls for production (fetch all)
            max_results_pattern = r'max_results\s*=\s*\d+'
            if re.search(max_results_pattern, production_code):
                production_code = re.sub(max_results_pattern, '', production_code)
                # Clean up any trailing comma/whitespace issues
                production_code = re.sub(r',\s*\)', ')', production_code)
                optimizations_applied.append("Removed max_results limit for production (fetch all data)")
        
        return {
            "production_code": production_code,
            "code_explanation": f"Production version of test code with optimizations",
            "optimizations_applied": optimizations_applied,
            "original_test_code": test_code
        }
    
    # ========================================================================
    # Tool 8: STOP Execution (NEW - for graceful termination)
    # ========================================================================
    
    async def stop_execution(
        reason: str,
        user_message: str,
        attempted_steps: List[str]
    ) -> Dict[str, Any]:
        """
        STOP execution and return a final result when unable to proceed.
        
        Call this tool when you've hit a circuit breaker limit, exhausted all approaches,
        or determined that the query cannot be answered with available data.
        
        This gracefully terminates the agent run and returns a clear message to the user.
        
        Args:
            reason: Internal reason for stopping (e.g., "SQL circuit breaker hit", "Data not available")
            user_message: Clear message to show the user explaining why we couldn't answer
            attempted_steps: List of steps you tried before stopping
        
        Returns:
            Stop signal that will terminate the agent
        """
        logger.warning(f"[{deps.correlation_id}] 🛑 STOP_EXECUTION called: {reason}")
        logger.info(f"[{deps.correlation_id}] User message: {user_message}")
        logger.info(f"[{deps.correlation_id}] Attempted steps: {attempted_steps}")
        
        # If progress callback is provided, send stop event to frontend
        if hasattr(deps, 'progress_callback') and deps.progress_callback:
            await deps.progress_callback({
                "type": "agent_stopped",
                "reason": reason,
                "user_message": user_message,
                "attempted_steps": attempted_steps,
                "timestamp": time.time()
            })
        
        return {
            "stop": True,
            "reason": reason,
            "user_message": user_message,
            "attempted_steps": attempted_steps,
            "final_result": ExecutionResult(
                success=False,
                results=None,
                execution_plan=f"Attempted: {', '.join(attempted_steps)}",
                steps_taken=attempted_steps,
                error=user_message,
                complete_production_code=""
            )
        }
    
    # Add all tools to the toolset (8 tools total)
    toolset.tool(log_progress)  # Tool 7: Progress logging
    toolset.tool(stop_execution)  # Tool 8: Stop execution (NEW)
    toolset.tool(load_sql_schema)  # Tool 1
    toolset.tool(load_comprehensive_api_endpoints)  # Tool 2
    toolset.tool(filter_endpoints_by_operations)  # Tool 3 (RENAMED from filter_endpoints_by_entities)
    toolset.tool(get_sql_code_generation_prompt)  # Tool 4
    toolset.tool(get_api_code_generation_prompt)  # Tool 5
    toolset.tool(execute_test_query)  # Tool 6
    # Note: generate_production_code removed - agent synthesizes final script directly
    
    return toolset

# ============================================================================
# ReAct Agent Definition
# ============================================================================

# Load system prompt from file
PROMPT_FILE = Path(__file__).parent / "prompts" / "one_react_agent_prompt.txt"

try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        BASE_SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logger.warning(f"Prompt file not found: {PROMPT_FILE}. Using default prompt.")
    BASE_SYSTEM_PROMPT = "You are a ReAct agent for Okta query execution."

# Create the ReAct agent using the same pattern as api_code_gen_agent
react_agent = Agent(
    model,  # Use model from model_pickerdaisy taylor
    
    instructions=BASE_SYSTEM_PROMPT,  # Static base instructions
    output_type=ExecutionResult,
    deps_type=ReactAgentDependencies,
    retries=0  # No retries to avoid wasting money on failed attempts
)

@react_agent.instructions  
def create_dynamic_instructions(ctx: RunContext[ReactAgentDependencies]) -> str:
    """Create dynamic instructions with context from dependencies"""
    deps = ctx.deps
    
    # Build dynamic context without the schema (loaded on-demand via Tool 1)
    dynamic_context = f"""

DYNAMIC CONTEXT FOR THIS REQUEST:
- User Query: {deps.user_query}
- Correlation ID: {deps.correlation_id}
- Available API Endpoints: {len(deps.endpoints)} total

⚠️ IMPORTANT REMINDER - CODE GENERATION WORKFLOW:
1. When you need database data:
   - FIRST: Call load_sql_schema() to see what tables and columns are available
   - SECOND: Call get_sql_code_generation_prompt(query_description, limit=3) to get SQL generation rules
   - THIRD: READ the returned guidance carefully
   - FOURTH: WRITE your SQL code using the schema and generation rules
   - FIFTH: Call execute_test_query(your_code, "sql")

2. When you need to generate Python SDK code:
   - FIRST: Call get_api_code_generation_prompt(query_description, endpoints, max_results=3)
   - SECOND: READ the returned data carefully
   - THIRD: WRITE your Python code based on that guidance
   - FOURTH: Call execute_test_query(your_code, "python_sdk")

The schema above shows you EXACTLY what tables (users, groups, applications, etc.) and 
columns exist in each table. DO NOT invent names - use only what you see above.

Remember to follow the workflow:
1. Load SQL schema first (unless user says "API only")
2. Determine if data is in SQLite database or needs API
3. Load comprehensive API endpoints if needed
4. Filter to specific entities
5. Get code generation prompt (Tool 4 or 5)
6. Generate YOUR code using the prompt guidance
7. Execute and inspect results
8. Generate production code
9. Return ExecutionResult
"""
    
    return dynamic_context

# ============================================================================
# Main Execution Function
# ============================================================================

async def execute_react_query(
    user_query: str,
    deps: ReactAgentDependencies
) -> ExecutionResult:
    """
    Execute user query using ReAct agent with 7 tools.
    
    Args:
        user_query: Natural language query from user
        deps: Dependencies for agent (endpoints, schema, clients, etc.)
    
    Returns:
        ExecutionResult with success status and results
    """
    logger.info(f"[{deps.correlation_id}] Starting ReAct agent execution for query: {user_query}")
    
    # Create toolset with dependencies
    toolset = create_react_toolset(deps)
    
    # Run agent with toolset
    result = await react_agent.run(
        user_query,
        deps=deps,
        toolsets=[toolset]  # Pass toolset as list
    )
    
    # Access the output from the result (PydanticAI returns output, not data)
    execution_result = result.output
    
    # Log synthesis phase completion
    if execution_result.complete_production_code:
        logger.info(f"[{deps.correlation_id}] ✅ SYNTHESIS COMPLETE: Generated final production code ({len(execution_result.complete_production_code)} chars)")
    else:
        logger.warning(f"[{deps.correlation_id}] ⚠️ SYNTHESIS INCOMPLETE: No production code generated")
    
    # Log token usage (accumulated across all LLM calls)
    if result.usage():
        usage = result.usage()
        logger.info(f"[{deps.correlation_id}] Token Usage: {usage.input_tokens} input, {usage.output_tokens} output, {usage.total_tokens} total (across {usage.requests} API calls)")
        
        # NEW: Report token usage via SSE callback
        if hasattr(deps, 'step_tokens_callback') and deps.step_tokens_callback:
            await deps.step_tokens_callback({
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "requests": usage.requests
            })
    
    logger.info(f"[{deps.correlation_id}] ReAct agent completed: success={execution_result.success}")
    
    # Return both execution result and usage info
    return execution_result, result.usage()
