"""
Enhanced GraphDB Schema Definition (v2) - Optimized for LLM Query Generation

Key Design Principles:
1. Rich node properties to minimize JOIN-like queries
2. Explicit relationship types with semantic meaning
3. Relationship properties capture assignment context
4. Application type-specific properties (SAML vs OIDC)
5. Policy-to-app one-to-many relationships
6. Device ownership with management status
7. Group source tracking (AD/LDAP/Okta)

This schema is designed to make LLM-generated Cypher queries:
- More intuitive (relationship names match natural language)
- More accurate (explicit types prevent confusion)
- More efficient (properties reduce multi-hop queries)
"""

import kuzu
from pathlib import Path
from src.utils.logging import get_logger

logger = get_logger(__name__)

ENHANCED_GRAPH_SCHEMA = """
-- ==============================================================================
-- USER NODE
-- ==============================================================================
-- Represents an Okta user with profile, status, and custom attributes
-- ALL fields from models.py User table preserved
-- LLM Context: "Users can be assigned to apps directly or via group memberships"
-- ==============================================================================
CREATE NODE TABLE User (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Identity & Contact
    display_name STRING,
    email STRING,
    login STRING,
    first_name STRING,
    last_name STRING,
    mobile_phone STRING,
    primary_phone STRING,
    
    -- Employment & Organization
    employee_number STRING,
    department STRING,
    title STRING,
    organization STRING,
    manager STRING,              -- Manager's login (can be used to find manager User node)
    user_type STRING,            -- Employee, Contractor, etc.
    country_code STRING,
    
    -- Account Status
    status STRING,               -- ACTIVE, SUSPENDED, DEPROVISIONED, STAGED, PROVISIONED, PASSWORD_RESET, PASSWORD_EXPIRED, LOCKED_OUT
    
    -- Timestamps (all from models.py)
    created_at TIMESTAMP,        -- API timestamp
    last_updated_at TIMESTAMP,   -- API timestamp
    password_changed_at TIMESTAMP,
    status_changed_at TIMESTAMP,
    last_synced_at TIMESTAMP,    -- Local sync timestamp
    updated_at TIMESTAMP,        -- Local tracking timestamp
    
    -- Custom Attributes Strategy: DYNAMIC PROPERTIES
    -- Custom attributes from OKTA_USER_CUSTOM_ATTRIBUTES are stored as individual properties
    -- Property names = actual Okta custom attribute names (e.g., "SLT_DEPARTMENT", "costCenter")
    -- This makes the schema self-documenting and LLM-friendly
    -- 
    -- Example with OKTA_USER_CUSTOM_ATTRIBUTES=SLT_DEPARTMENT,costCenter,employeeType:
    --   u.SLT_DEPARTMENT = "Engineering"     (actual property name)
    --   u.costCenter = "12345"               (actual property name)  
    --   u.employeeType = "Contractor"        (actual property name)
    --
    -- Note: Custom attribute properties are created dynamically at sync time
    -- No pre-defined schema needed - Kuzu supports schema-less properties
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- GROUP NODE
-- ==============================================================================
-- Represents an Okta group (can be synced from AD/LDAP or native to Okta)
-- ALL fields from models.py Group table preserved
-- LLM Context: "Groups can be assigned to apps, policies. Users belong to groups."
-- ==============================================================================
CREATE NODE TABLE OktaGroup (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Group Identity
    name STRING,
    description STRING,
    display_name STRING,         -- Friendly name for visualization
    
    -- Group Source (for LLM understanding)
    source_type STRING,          -- AD, LDAP, OKTA_NATIVE, APP_GROUP, BUILT_IN
    source_id STRING,            -- External directory ID if synced
    
    -- Group Type
    group_type STRING,           -- OKTA_GROUP, BUILT_IN, APP_GROUP
    
    -- Timestamps (from models.py BaseModel)
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    updated_at TIMESTAMP,
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- APPLICATION NODE
-- ==============================================================================
-- Represents an Okta application (SAML or OIDC)
-- ALL fields from models.py Application table preserved
-- LLM Context: "Apps can be SAML or OIDC. Users assigned directly or via groups. Each app has one policy."
-- ==============================================================================
CREATE NODE TABLE Application (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Application Identity
    name STRING,
    label STRING,                -- User-visible name (what users see in frontend)
    display_name STRING,         -- Friendly name for visualization
    
    -- Application Status
    status STRING,               -- ACTIVE, INACTIVE
    
    -- Authentication Protocol
    sign_on_mode STRING,         -- SAML_2_0, OPENID_CONNECT, SECURE_PASSWORD_STORE, AUTO_LOGIN, etc.
    
    -- URLs and Integration (from models.py)
    metadata_url STRING,         -- SAML metadata URL
    sign_on_url STRING,
    audience STRING,             -- SAML audience
    destination STRING,          -- SAML destination
    
    -- Authentication Settings (from models.py)
    signing_kid STRING,          -- Key ID for signing
    username_template STRING,
    username_template_type STRING,
    
    -- Assignment Settings (from models.py)
    implicit_assignment BOOLEAN, -- Auto-assign to all users?
    admin_note STRING,           -- TEXT in SQL, STRING in Kuzu
    
    -- SAML Settings (from models.py)
    attribute_statements STRING[],  -- JSON array of SAML attributes
    honor_force_authn BOOLEAN,
    
    -- Visibility (from models.py)
    hide_ios BOOLEAN,
    hide_web BOOLEAN,
    
    -- Policy Reference (from models.py)
    policy_id STRING,            -- FK to Policy.okta_id (each app has ONE policy)
    
    -- Timestamps (from models.py)
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    updated_at TIMESTAMP,        -- Local tracking
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- POLICY NODE
-- ==============================================================================
-- Represents an Okta policy (sign-on, MFA, password, etc.)
-- Cardinality: One policy per okta_id per tenant
-- LLM Context: "A policy can be assigned to multiple apps. Each app has only one policy. Policies have rules with network zones and MFA requirements."
-- ==============================================================================
CREATE NODE TABLE Policy (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Policy Identity
    name STRING,
    description STRING,
    display_name STRING,
    
    -- Policy Type
    type STRING,                 -- OKTA_SIGN_ON, PASSWORD, MFA_ENROLL, ACCESS_POLICY, etc.
    
    -- Policy Settings
    status STRING,               -- ACTIVE, INACTIVE
    priority INT32,              -- Lower number = higher priority
    system BOOLEAN,              -- System-managed policy?
    
    -- Timestamps
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- POLICY RULE NODE (NEW - Critical for LLM understanding!)
-- ==============================================================================
-- Represents individual rules within a policy
-- Cardinality: Multiple rules per policy
-- LLM Context: "Rules define allow/deny based on network zones (IP ranges) and MFA requirements. Priority matters."
-- ==============================================================================
CREATE NODE TABLE PolicyRule (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    policy_id STRING,            -- FK to Policy.okta_id
    
    -- Rule Identity
    name STRING,
    
    -- Rule Evaluation
    priority INT32,              -- Lower = evaluated first
    status STRING,               -- ACTIVE, INACTIVE
    
    -- Access Decision
    access STRING,               -- ALLOW, DENY
    
    -- MFA Requirements
    require_mfa BOOLEAN,
    mfa_lifetime_minutes INT32,
    mfa_prompt STRING,           -- ALWAYS, DEVICE, SESSION
    factor_types STRING[],       -- Array of allowed factor types
    
    -- Network Constraints
    network_connection STRING,   -- ANYWHERE, ZONE, ON_NETWORK, OFF_NETWORK
    network_zone_ids STRING[],   -- Array of network zone IDs
    network_zone_names STRING[], -- Array of network zone names (denormalized for LLM)
    network_includes STRING[],   -- IP ranges included
    network_excludes STRING[],   -- IP ranges excluded
    
    -- User/Group Conditions
    user_ids STRING[],           -- Specific users this rule applies to
    group_ids STRING[],          -- Specific groups this rule applies to
    
    -- Session Management
    session_lifetime_minutes INT32,
    session_persistent BOOLEAN,
    
    -- Timestamps
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP
);

-- ==============================================================================
-- FACTOR NODE
-- ==============================================================================
-- Represents an MFA factor/authenticator
-- Cardinality: One factor per okta_id per tenant
-- LLM Context: "Users can enroll in multiple MFA factors. Each factor has a type and status."
-- ==============================================================================
CREATE NODE TABLE Factor (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Factor Identity
    factor_type STRING,          -- sms, email, call, push, token:software:totp, signed_nonce, webauthn
    provider STRING,             -- OKTA, GOOGLE, DUO, RSA, etc.
    vendor_name STRING,          -- Google Authenticator, Okta Verify, etc.
    authenticator_name STRING,   -- Friendly name
    
    -- Factor Status
    status STRING,               -- ACTIVE, INACTIVE, PENDING_ACTIVATION
    
    -- Device-specific (for mobile factors)
    device_type STRING,          -- Android, iOS, etc.
    device_name STRING,
    platform STRING,
    
    -- Contact methods (for SMS/Email/Call)
    phone_number STRING,
    email STRING,
    
    -- Timestamps
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- DEVICE NODE
-- ==============================================================================
-- Represents a physical device
-- Cardinality: One device per okta_id per tenant
-- LLM Context: "A device can be managed, unmanaged, or registered. Mostly one user per device, but can be shared."
-- ==============================================================================
CREATE NODE TABLE Device (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Device Identity
    display_name STRING,
    serial_number STRING,
    udid STRING,                 -- Unique device identifier
    
    -- Device Type
    platform STRING,             -- ANDROID, IOS, WINDOWS, MACOS, etc.
    manufacturer STRING,         -- Apple, Samsung, Dell, etc.
    model STRING,
    os_version STRING,
    
    -- Device Status
    status STRING,               -- ACTIVE, CREATED, SUSPENDED, DEACTIVATED
    registered BOOLEAN,
    
    -- Security Settings
    secure_hardware_present BOOLEAN,
    disk_encryption_type STRING, -- USER, FULL, NONE
    
    -- Timestamps
    registered_at TIMESTAMP,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP,
    
    -- Sync metadata
    is_deleted BOOLEAN
);

-- ==============================================================================
-- NETWORK ZONE NODE (NEW - Critical for policy rules!)
-- ==============================================================================
-- Represents network zones (IP ranges) used in policy rules
-- Cardinality: One zone per okta_id per tenant
-- LLM Context: "Network zones define IP ranges for policy rules. Rules can allow/deny based on zones."
-- ==============================================================================
CREATE NODE TABLE NetworkZone (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    
    -- Zone Identity
    name STRING,
    
    -- Zone Type
    type STRING,                 -- IP, DYNAMIC
    status STRING,               -- ACTIVE, INACTIVE
    
    -- IP Ranges (for IP zones)
    gateway_ips STRING[],        -- Array of gateway IPs
    proxy_ips STRING[],          -- Array of proxy IPs
    
    -- Location (for DYNAMIC zones)
    locations STRING[],          -- Array of location codes
    asns STRING[],               -- Array of ASNs
    
    -- Timestamps
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP
);

-- ==============================================================================
-- RELATIONSHIPS
-- ==============================================================================

-- User → Group Membership
-- LLM Context: "User belongs to group"
CREATE REL TABLE MEMBER_OF (
    FROM User TO OktaGroup,
    tenant_id STRING,
    assigned_at TIMESTAMP,
    membership_type STRING       -- DIRECT, IMPORTED (from AD/LDAP), RULE_BASED
);

-- User → Application (Direct Assignment)
-- LLM Context: "User has access to app (directly assigned)"
CREATE REL TABLE HAS_ACCESS (
    FROM User TO Application,
    tenant_id STRING,
    
    -- Assignment metadata
    assignment_id STRING,        -- Okta assignment ID
    app_instance_id STRING,      -- App instance ID
    scope STRING,                -- USER, GROUP
    
    -- Assignment settings
    credentials_setup BOOLEAN,
    hidden BOOLEAN,              -- Hidden from user's app portal?
    
    assigned_at TIMESTAMP
);

-- Group → Application (Group Assignment)
-- LLM Context: "Group has access to app (all members can use it)"
CREATE REL TABLE GROUP_HAS_ACCESS (
    FROM OktaGroup TO Application,
    tenant_id STRING,
    
    -- Assignment metadata
    assignment_id STRING,
    priority INT32,              -- Assignment priority (0 = highest)
    
    assigned_at TIMESTAMP
);

-- User → Factor (MFA Enrollment)
-- LLM Context: "User has enrolled in this MFA factor"
CREATE REL TABLE ENROLLED (
    FROM User TO Factor,
    tenant_id STRING,
    enrolled_at TIMESTAMP,
    last_verified_at TIMESTAMP
);

-- User → Device (Device Ownership)
-- LLM Context: "User owns/uses this device"
CREATE REL TABLE OWNS (
    FROM User TO Device,
    tenant_id STRING,
    
    -- Device management
    management_status STRING,    -- NOT_MANAGED, MANAGED, etc.
    screen_lock_type STRING,     -- BIOMETRIC, PIN, PASSWORD, NONE
    
    registered_at TIMESTAMP,
    user_device_created_at TIMESTAMP
);

-- Application → Policy (Policy Assignment)
-- LLM Context: "App is governed by this policy (one policy per app)"
CREATE REL TABLE GOVERNED_BY (
    FROM Application TO Policy,
    tenant_id STRING,
    assigned_at TIMESTAMP
);

-- Policy → PolicyRule (Rule Membership)
-- LLM Context: "Policy contains this rule (rules evaluated by priority)"
CREATE REL TABLE CONTAINS_RULE (
    FROM Policy TO PolicyRule,
    tenant_id STRING,
    rule_priority INT32,         -- Denormalized for faster queries
    created_at TIMESTAMP
);

-- PolicyRule → NetworkZone (Zone Reference)
-- LLM Context: "Rule applies to this network zone"
CREATE REL TABLE APPLIES_TO_ZONE (
    FROM PolicyRule TO NetworkZone,
    tenant_id STRING,
    include_or_exclude STRING    -- INCLUDE, EXCLUDE
);

-- PolicyRule → User (User-Specific Rule)
-- LLM Context: "Rule applies to this specific user"
CREATE REL TABLE APPLIES_TO_USER (
    FROM PolicyRule TO User,
    tenant_id STRING
);

-- PolicyRule → Group (Group-Specific Rule)
-- LLM Context: "Rule applies to this group"
CREATE REL TABLE APPLIES_TO_GROUP (
    FROM PolicyRule TO OktaGroup,
    tenant_id STRING
);

-- User → User (Manager Relationship)
-- LLM Context: "User reports to this manager"
CREATE REL TABLE REPORTS_TO (
    FROM User TO User,
    tenant_id STRING,
    established_at TIMESTAMP
);
"""


def initialize_enhanced_schema(db_path: str = "./db/tenant_graph_v1.db") -> tuple:
    """
    Initialize GraphDB with enhanced Okta schema optimized for LLM queries
    
    Args:
        db_path: Path to the graph database file
        
    Returns:
        Tuple of (database, connection) objects
    """
    logger.info(f"Initializing Enhanced GraphDB schema at: {db_path}")
    
    # Ensure directory exists
    db_path_obj = Path(db_path)
    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize database
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    
    # Execute schema creation
    statements = [s.strip() for s in ENHANCED_GRAPH_SCHEMA.strip().split(';') if s.strip()]
    
    for statement in statements:
        # Skip comments
        if statement.startswith('--'):
            continue
            
        try:
            conn.execute(statement)
            # Extract table name for logging
            if 'CREATE NODE TABLE' in statement or 'CREATE REL TABLE' in statement:
                table_name = statement.split('TABLE')[1].split('(')[0].strip()
                logger.info(f"✓ Created: {table_name}")
        except Exception as e:
            logger.error(f"✗ Error executing statement: {e}")
            logger.debug(f"  Statement: {statement[:100]}...")
    
    # Create performance indexes
    create_enhanced_indexes(conn)
    
    logger.info("Enhanced GraphDB schema initialized successfully!")
    return db, conn


def create_enhanced_indexes(conn: kuzu.Connection):
    """
    Create essential performance indexes for LLM query patterns
    
    Strategy: Index only the MOST frequently queried properties
    - Primary keys are automatically indexed
    - Focus on user lookups (email, login, status)
    - Focus on entity names (groups, apps)
    - Minimal indexes = faster writes, less storage
    """
    logger.info("Creating essential performance indexes...")
    
    indexes = [
        # ==============================================================================
        # USER INDEXES - Critical for user lookups
        # ==============================================================================
        
        # Email lookup (MOST common query)
        "CREATE INDEX idx_user_email FOR (u:User) ON (u.email)",
        
        # Login lookup (alternative identifier)
        "CREATE INDEX idx_user_login FOR (u:User) ON (u.login)",
        
        # Status filtering (active vs inactive)
        "CREATE INDEX idx_user_status FOR (u:User) ON (u.status)",
        
        # Custom attribute lookup (first custom attribute only - most frequently queried)
        "CREATE INDEX idx_user_custom_attrib_1 FOR (u:User) ON (u.custom_attrib_1)",
        
        # ==============================================================================
        # GROUP INDEXES - Critical for group lookups
        # ==============================================================================
        
        # Group name lookup (MOST common query)
        "CREATE INDEX idx_group_name FOR (g:OktaGroup) ON (g.name)",
        
        # ==============================================================================
        # APPLICATION INDEXES - Critical for app lookups
        # ==============================================================================
        
        # Application label lookup (user-visible name)
        "CREATE INDEX idx_app_label FOR (a:Application) ON (a.label)",
        
        # Status filtering (active apps only)
        "CREATE INDEX idx_app_status FOR (a:Application) ON (a.status)",
        
        # ==============================================================================
        # POLICY INDEXES - For policy lookups
        # ==============================================================================
        
        # Policy name lookup
        "CREATE INDEX idx_policy_name FOR (p:Policy) ON (p.name)",
        
        # ==============================================================================
        # FACTOR INDEXES - For MFA queries
        # ==============================================================================
        
        # Factor type filtering (most common factor query)
        "CREATE INDEX idx_factor_type FOR (f:Factor) ON (f.factor_type)",
    ]
    
    # Execute index creation
    created = 0
    skipped = 0
    errors = 0
    
    for index_stmt in indexes:
        try:
            conn.execute(index_stmt)
            # Extract index name for logging
            index_name = index_stmt.split('CREATE INDEX')[1].split('FOR')[0].strip()
            logger.debug(f"✓ Created index: {index_name}")
            created += 1
        except Exception as e:
            error_msg = str(e).lower()
            if 'already exists' in error_msg or 'duplicate' in error_msg:
                logger.debug(f"⊙ Index already exists: {index_stmt[:60]}...")
                skipped += 1
            else:
                logger.warning(f"✗ Error creating index: {e}")
                logger.debug(f"  Statement: {index_stmt}")
                errors += 1
    
    logger.info(f"Index creation complete: {created} created, {skipped} skipped, {errors} errors")
    logger.info(f"Essential indexes ({created + skipped} total):")
    logger.info("  ✓ User: email, login, status")
    logger.info("  ✓ Group: name")
    logger.info("  ✓ Application: label, status")
    logger.info("  ✓ Policy: name")
    logger.info("  ✓ Factor: factor_type")



def get_graph_schema_description() -> str:
    """
    Get a comprehensive description of the GraphDB schema for LLM query generation.
    
    This function returns the schema documentation in a format optimized for 
    LLMs to understand the graph structure, node types, relationships, and 
    properties for generating accurate Cypher queries.
    
    Returns:
        str: Complete schema description with node definitions, relationships,
             properties, indexes, and query examples
    """
    
    schema_description = """
# OKTA GRAPHDB SCHEMA DOCUMENTATION (Kuzu v0.11.2)

## OVERVIEW
This is a property graph representing Okta identity and access management data.
The schema uses explicit relationship types for semantic clarity and includes
all fields from the original SQLite models for comprehensive data access.

## NODE TYPES (8 total)

### 1. User
Represents an Okta user account with profile, status, and custom attributes.

**Properties** (23 base properties + dynamic custom attributes):
- okta_id (STRING, PRIMARY KEY) - Unique Okta user identifier (e.g., '00u...')
- tenant_id (STRING) - Tenant identifier
- display_name (STRING) - Full display name
- email (STRING) - User's primary email address
- login (STRING) - User's login username
- first_name (STRING) - Given name
- last_name (STRING) - Family name
- mobile_phone (STRING) - Mobile phone number
- primary_phone (STRING) - Primary phone number
- employee_number (STRING) - Employee ID
- department (STRING) - Department name
- title (STRING) - Job title
- organization (STRING) - Organization name
- manager (STRING) - Manager's login username (can be used to find manager User node)
- user_type (STRING) - Type of user account (Employee, Contractor, etc.)
- country_code (STRING) - Country code
- status (STRING) - User account status (ACTIVE, SUSPENDED, DEPROVISIONED, STAGED, PROVISIONED, PASSWORD_RESET, PASSWORD_EXPIRED, LOCKED_OUT)
- created_at (TIMESTAMP) - API timestamp
- last_updated_at (TIMESTAMP) - API timestamp
- password_changed_at (TIMESTAMP) - Password change timestamp
- status_changed_at (TIMESTAMP) - Status change timestamp
- last_synced_at (TIMESTAMP) - Local sync timestamp
- updated_at (TIMESTAMP) - Local tracking timestamp
- is_deleted (BOOLEAN) - Sync metadata flag

**Dynamic Custom Attributes** (created at sync time from OKTA_USER_CUSTOM_ATTRIBUTES env variable):
- Custom attribute properties are created dynamically at sync time
- Property names match actual Okta custom attribute names (e.g., SLT_DEPARTMENT, costCenter, employeeType)
- Access them directly: `WHERE u.SLT_DEPARTMENT = 'Engineering'`
- No pre-defined schema needed - Kuzu supports schema-less properties

**Indexed Properties**: email, login, status, custom_attrib_1

### 2. OktaGroup
Represents an Okta group for organizing users and managing access.

**Properties** (13):
- okta_id (STRING, PRIMARY KEY) - Unique group identifier (e.g., '00g...')
- tenant_id (STRING) - Tenant identifier
- name (STRING) - Group name
- description (STRING) - Group description
- display_name (STRING) - Friendly name for visualization
- source_type (STRING) - Source type (AD, LDAP, OKTA_NATIVE, APP_GROUP, BUILT_IN)
- source_id (STRING) - External directory ID if synced
- group_type (STRING) - Type of group (OKTA_GROUP, BUILT_IN, APP_GROUP)
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp
- last_synced_at (TIMESTAMP) - Last sync timestamp
- updated_at (TIMESTAMP) - Local tracking timestamp
- is_deleted (BOOLEAN) - Sync metadata flag

**Indexed Properties**: name

### 3. Application
Represents an application integrated with Okta for SSO/authentication.

**Properties** (25):
- okta_id (STRING, PRIMARY KEY) - Unique application identifier (e.g., '0oa...')
- tenant_id (STRING) - Tenant identifier
- name (STRING) - Technical application name
- label (STRING) - User-visible name (what users see in frontend)
- display_name (STRING) - Friendly name for visualization
- status (STRING) - Application status (ACTIVE, INACTIVE)
- sign_on_mode (STRING) - Authentication method (SAML_2_0, OPENID_CONNECT, SECURE_PASSWORD_STORE, AUTO_LOGIN, etc.)
- metadata_url (STRING) - SAML metadata URL
- sign_on_url (STRING) - Sign-on URL
- audience (STRING) - SAML audience
- destination (STRING) - SAML destination
- signing_kid (STRING) - Key ID for signing
- username_template (STRING) - Username template
- username_template_type (STRING) - Username template type
- implicit_assignment (BOOLEAN) - Auto-assign to all users?
- admin_note (STRING) - Admin notes
- attribute_statements (STRING[]) - JSON array of SAML attributes
- honor_force_authn (BOOLEAN) - Honor force authentication
- hide_ios (BOOLEAN) - Hide on iOS
- hide_web (BOOLEAN) - Hide on web
- policy_id (STRING) - FK to Policy.okta_id (each app has ONE policy)
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp
- last_synced_at (TIMESTAMP) - Last sync timestamp
- updated_at (TIMESTAMP) - Local tracking timestamp
- is_deleted (BOOLEAN) - Sync metadata flag

**Indexed Properties**: label, status

### 4. Policy
Represents an Okta authentication or authorization policy.

**Properties** (11):
- okta_id (STRING, PRIMARY KEY) - Unique policy identifier
- tenant_id (STRING) - Tenant identifier
- name (STRING) - Policy name
- description (STRING) - Policy description
- display_name (STRING) - Display name
- type (STRING) - Type of policy (OKTA_SIGN_ON, PASSWORD, MFA_ENROLL, ACCESS_POLICY, etc.)
- status (STRING) - Policy status (ACTIVE, INACTIVE)
- priority (INT32) - Policy priority order (lower number = higher priority)
- system (BOOLEAN) - System-managed policy?
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp
- last_synced_at (TIMESTAMP) - Last sync timestamp
- is_deleted (BOOLEAN) - Sync metadata flag

**Indexed Properties**: name

### 5. PolicyRule
Represents a rule within a policy with specific conditions and actions.

**Properties** (21):
- okta_id (STRING, PRIMARY KEY) - Unique rule identifier
- tenant_id (STRING) - Tenant identifier
- policy_id (STRING) - FK to Policy.okta_id
- name (STRING) - Rule name
- priority (INT32) - Rule priority order (lower = evaluated first)
- status (STRING) - Rule status (ACTIVE, INACTIVE)
- access (STRING) - Access decision (ALLOW, DENY)
- require_mfa (BOOLEAN) - Whether MFA is required
- mfa_lifetime_minutes (INT32) - MFA lifetime in minutes
- mfa_prompt (STRING) - MFA prompt setting (ALWAYS, DEVICE, SESSION)
- factor_types (STRING[]) - Array of allowed factor types
- network_connection (STRING) - Network connection type (ANYWHERE, ZONE, ON_NETWORK, OFF_NETWORK)
- network_zone_ids (STRING[]) - Array of network zone IDs
- network_zone_names (STRING[]) - Array of network zone names (denormalized for LLM)
- network_includes (STRING[]) - IP ranges included
- network_excludes (STRING[]) - IP ranges excluded
- user_ids (STRING[]) - Specific users this rule applies to
- group_ids (STRING[]) - Specific groups this rule applies to
- session_lifetime_minutes (INT32) - Session lifetime in minutes
- session_persistent (BOOLEAN) - Session persistence setting
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp

### 6. Factor
Represents an MFA factor/device enrolled by a user.

**Properties** (14):
- okta_id (STRING, PRIMARY KEY) - Unique factor identifier
- factor_type (STRING) - Type of MFA (sms, call, email, push, totp, webauthn, etc.)
- provider (STRING) - MFA provider (OKTA, GOOGLE, RSA, etc.)
- vendor_name (STRING) - Vendor name
- device_type (STRING) - Device type for factor (Android, iOS, etc.)
- device_name (STRING) - Device name (e.g., "Samsung Galaxy S24", "iPhone 15 Pro")
- platform (STRING) - Device platform
- status (STRING) - Factor status (ACTIVE, INACTIVE, PENDING_ACTIVATION, etc.)
- phone_number (STRING) - Phone number for SMS/voice factors
- email (STRING) - Email for email factors
- credential_id (STRING) - Credential identifier
- verification (STRING) - Verification details
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp
- last_synced_at (TIMESTAMP) - Last sync timestamp

**Indexed Properties**: factor_type

### 7. Device
Represents a device registered with Okta.

**Properties** (17):
- okta_id (STRING, PRIMARY KEY) - Unique device identifier
- tenant_id (STRING) - Tenant identifier
- display_name (STRING) - User-friendly device name
- serial_number (STRING) - Device serial number
- udid (STRING) - Unique device identifier
- platform (STRING) - Platform (ANDROID, IOS, WINDOWS, MACOS, etc.)
- manufacturer (STRING) - Device manufacturer (Apple, Samsung, Dell, etc.)
- model (STRING) - Device model
- os_version (STRING) - Operating system version
- status (STRING) - Device status (ACTIVE, CREATED, SUSPENDED, DEACTIVATED)
- registered (BOOLEAN) - Registration status
- secure_hardware_present (BOOLEAN) - Secure hardware present
- disk_encryption_type (STRING) - Disk encryption type (USER, FULL, NONE)
- registered_at (TIMESTAMP) - Registration timestamp
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp
- last_synced_at (TIMESTAMP) - Last sync timestamp
- is_deleted (BOOLEAN) - Sync metadata flag

### 8. NetworkZone
Represents a network zone (IP allowlist/blocklist) in Okta.

**Properties** (10):
- okta_id (STRING, PRIMARY KEY) - Unique zone identifier
- tenant_id (STRING) - Tenant identifier
- name (STRING) - Zone name
- type (STRING) - Zone type (IP, DYNAMIC)
- status (STRING) - Zone status (ACTIVE, INACTIVE)
- gateway_ips (STRING[]) - Array of gateway IPs
- proxy_ips (STRING[]) - Array of proxy IPs
- locations (STRING[]) - Array of location codes
- asns (STRING[]) - Array of ASNs
- created_at (TIMESTAMP) - Creation timestamp
- last_updated_at (TIMESTAMP) - Last update timestamp

## RELATIONSHIP TYPES (11 total)

### 1. MEMBER_OF
User→OktaGroup: User is a member of a group
**Properties**:
- tenant_id (STRING) - Tenant identifier
- assigned_at (TIMESTAMP) - Assignment timestamp
- membership_type (STRING) - Membership type (DIRECT, IMPORTED from AD/LDAP, RULE_BASED)
**Example**: `(u:User)-[:MEMBER_OF]->(g:OktaGroup)`

### 2. HAS_ACCESS
User→Application: User has **direct** access to an application.
**Note**: For complete access checks, you MUST also check for indirect access via the `GROUP_HAS_ACCESS` relationship. See the "CRITICAL QUERY PATTERNS" section for the mandatory UNION pattern.
**Properties**:
- tenant_id (STRING) - Tenant identifier
- assignment_id (STRING) - Okta assignment ID
- app_instance_id (STRING) - App instance ID
- scope (STRING) - Assignment scope (USER, GROUP)
- credentials_setup (BOOLEAN) - Credentials setup flag
- hidden (BOOLEAN) - Hidden from user's app portal?
- assigned_at (TIMESTAMP) - Assignment timestamp
**Example**: `(u:User)-[:HAS_ACCESS]->(a:Application)`

### 3. GROUP_HAS_ACCESS
OktaGroup→Application: Group has access to an application (group-based assignment)
**Properties**:
- tenant_id (STRING) - Tenant identifier
- assignment_id (STRING) - Okta assignment ID
- priority (INT32) - Assignment priority (0 = highest)
- assigned_at (TIMESTAMP) - Assignment timestamp
**Example**: `(g:OktaGroup)-[:GROUP_HAS_ACCESS]->(a:Application)`

### 4. ENROLLED
User→Factor: User has enrolled an MFA factor
**Properties**:
- tenant_id (STRING) - Tenant identifier
- enrolled_at (TIMESTAMP) - Enrollment timestamp
- last_verified_at (TIMESTAMP) - Last verification timestamp
**Example**: `(u:User)-[:ENROLLED]->(f:Factor)`

### 5. OWNS
User→Device: User owns a device
**Properties**:
- tenant_id (STRING) - Tenant identifier
- management_status (STRING) - Device management status (NOT_MANAGED, MANAGED, etc.)
- screen_lock_type (STRING) - Screen lock type (BIOMETRIC, PIN, PASSWORD, NONE)
- registered_at (TIMESTAMP) - Registration timestamp
- user_device_created_at (TIMESTAMP) - User device creation timestamp
**Example**: `(u:User)-[:OWNS]->(d:Device)`

### 6. GOVERNED_BY
Application→Policy: Application is governed by a policy
**Properties**:
- tenant_id (STRING) - Tenant identifier
- assigned_at (TIMESTAMP) - Assignment timestamp
**Example**: `(a:Application)-[:GOVERNED_BY]->(p:Policy)`

### 7. CONTAINS_RULE
Policy→PolicyRule: Policy contains a rule
**Properties**:
- tenant_id (STRING) - Tenant identifier
- rule_priority (INT32) - Rule priority (denormalized for faster queries)
- created_at (TIMESTAMP) - Creation timestamp
**Example**: `(p:Policy)-[:CONTAINS_RULE]->(r:PolicyRule)`

### 8. APPLIES_TO_ZONE
PolicyRule→NetworkZone: Rule applies to a network zone
**Properties**:
- tenant_id (STRING) - Tenant identifier
- include_or_exclude (STRING) - Include or exclude flag (INCLUDE, EXCLUDE)
**Example**: `(r:PolicyRule)-[:APPLIES_TO_ZONE]->(z:NetworkZone)`

### 9. APPLIES_TO_USER
PolicyRule→User: Rule applies to specific user
**Properties**:
- tenant_id (STRING) - Tenant identifier
**Example**: `(r:PolicyRule)-[:APPLIES_TO_USER]->(u:User)`

### 10. APPLIES_TO_GROUP
PolicyRule→OktaGroup: Rule applies to specific group
**Properties**:
- tenant_id (STRING) - Tenant identifier
**Example**: `(r:PolicyRule)-[:APPLIES_TO_GROUP]->(g:OktaGroup)`

### 11. REPORTS_TO
User→User: Manager/report hierarchy
**Properties**:
- tenant_id (STRING) - Tenant identifier
- established_at (TIMESTAMP) - Relationship establishment timestamp
**Example**: `(u:User)-[:REPORTS_TO]->(m:User)`

## CRITICAL QUERY PATTERNS

### Application Assignment Queries (MUST USE UNION)
When finding applications for a user, ALWAYS check BOTH:
1. Direct assignments: User→HAS_ACCESS→Application
2. Group-based assignments: User→MEMBER_OF→OktaGroup→GROUP_HAS_ACCESS→Application

**MANDATORY Pattern**:
```cypher
// Direct assignments
MATCH (u:User {email: 'user@example.com'})-[:HAS_ACCESS]->(a:Application)
WHERE a.status = 'ACTIVE'
RETURN u.email, a.label, 'Direct' AS assignment_type
UNION
// Group-based assignments
MATCH (u:User {email: 'user@example.com'})-[:MEMBER_OF]->(g:OktaGroup)-[:GROUP_HAS_ACCESS]->(a:Application)
WHERE a.status = 'ACTIVE'
RETURN u.email, a.label, g.name AS assignment_type
ORDER BY email, label
```

### Status Filtering Defaults
- Users: Filter to `status = 'ACTIVE'` by default (unless user asks for all statuses)
- Applications: Filter to `status = 'ACTIVE'` by default
- Groups: No status filter needed (no status field)

### Property Access
- Standard properties: Direct access (e.g., `u.email`, `u.department`)
- Custom attributes: Direct access (e.g., `u.custom_attrib_1`)
- All custom attribute names come from environment configuration

## ESSENTIAL INDEXES
The following properties are indexed for performance:
- User: email, login, status, custom_attrib_1
- OktaGroup: name
- Application: label, status
- Policy: name
- Factor: factor_type

## COMMON STATUS VALUES
- User: ACTIVE, SUSPENDED, DEPROVISIONED, LOCKED_OUT, PASSWORD_EXPIRED, PROVISIONED, STAGED, PASSWORD_RESET
- Application: ACTIVE, INACTIVE
- Factor: ACTIVE, INACTIVE, PENDING_ACTIVATION, ENROLLED
- Policy: ACTIVE, INACTIVE
- PolicyRule: ACTIVE, INACTIVE
- Device: ACTIVE, INACTIVE, SUSPENDED, DEACTIVATED

## COMMON FACTOR TYPES
- token:software:totp (Authenticator apps)
- sms (SMS text message)
- call (Voice call)
- email (Email verification)
- push (Push notification)
- signed_nonce (Okta Verify)
- webauthn (FIDO2/WebAuthn)
- token (Hardware token)
- token:hardware (Hardware token)
- u2f (Universal 2nd Factor)

## QUERY EXAMPLES

### Find user by email
```cypher
MATCH (u:User {email: 'user@example.com'})
RETURN u.okta_id, u.email, u.login, u.first_name, u.last_name, u.status
```

### Users in a group
```cypher
MATCH (u:User)-[:MEMBER_OF]->(g:OktaGroup {name: 'IT-Administrators'})
WHERE u.status = 'ACTIVE'
RETURN u.okta_id, u.email, u.login, u.first_name, u.last_name
ORDER BY u.last_name, u.first_name
```

### User's applications (direct + group-based)
```cypher
MATCH (u:User {email: 'user@example.com'})-[:HAS_ACCESS]->(a:Application)
WHERE a.status = 'ACTIVE'
RETURN u.email, a.label, a.okta_id, 'Direct' AS type
UNION
MATCH (u:User {email: 'user@example.com'})-[:MEMBER_OF]->(g:OktaGroup)-[:GROUP_HAS_ACCESS]->(a:Application)
WHERE a.status = 'ACTIVE'
RETURN u.email, a.label, a.okta_id, g.name AS type
ORDER BY label
```

### User's MFA factors
```cypher
MATCH (u:User {email: 'user@example.com'})-[:ENROLLED]->(f:Factor)
WHERE f.status = 'ACTIVE'
RETURN u.email, f.factor_type, f.provider, f.status
ORDER BY f.factor_type
```

### Manager's direct reports
```cypher
MATCH (m:User {email: 'manager@example.com'})<-[:REPORTS_TO]-(u:User)
WHERE u.status = 'ACTIVE'
RETURN u.okta_id, u.email, u.first_name, u.last_name, u.title
ORDER BY u.last_name, u.first_name
```

### Users with custom attribute value
```cypher
MATCH (u:User)
WHERE u.custom_attrib_1 = 'Engineering' AND u.status = 'ACTIVE'
RETURN u.okta_id, u.email, u.login, u.custom_attrib_1
ORDER BY u.last_name, u.first_name
```

### Application assignments summary
```cypher
MATCH (a:Application {label: 'Salesforce'})
OPTIONAL MATCH (u:User)-[:HAS_ACCESS]->(a)
WHERE u.status = 'ACTIVE'
OPTIONAL MATCH (g:OktaGroup)-[:GROUP_HAS_ACCESS]->(a)
RETURN a.okta_id, a.label, a.status,
       count(DISTINCT u) AS direct_users,
       count(DISTINCT g) AS assigned_groups
```
"""
    
    return schema_description
