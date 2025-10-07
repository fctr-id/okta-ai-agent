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


def initialize_enhanced_schema(db_path: str = "./graph_db/okta_graph.db") -> tuple:
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


# ==============================================================================
# LLM SCHEMA DOCUMENTATION
# ==============================================================================
# This will be provided to LLMs for query generation

LLM_SCHEMA_GUIDE = """
# Okta GraphDB Schema - LLM Query Generation Guide

## Node Types

### User
**Purpose:** Represents an Okta user
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `email` (STRING): User's email ⚡ INDEXED
- `login` (STRING): User's login ⚡ INDEXED
- `display_name` (STRING): Full name for visualization
- `status` (STRING): ACTIVE | SUSPENDED | DEPROVISIONED | STAGED | PROVISIONED | PASSWORD_RESET | PASSWORD_EXPIRED | LOCKED_OUT ⚡ INDEXED
- `department` (STRING): Department ⚡ INDEXED
- `user_type` (STRING): Employee, Contractor, etc. ⚡ INDEXED
- `manager` (STRING): Manager's login (use to find manager User node) ⚡ INDEXED
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `MATCH (u:User {email: $email})` - Email lookup
- `MATCH (u:User {login: $login})` - Login lookup  
- `WHERE u.status = 'ACTIVE'` - Status filter
- `WHERE u.department = 'Engineering'` - Department filter
- `WHERE u.tenant_id = $tenant AND u.status = 'ACTIVE'` - Composite filter

**Outgoing Relationships:**
- `MEMBER_OF` → OktaGroup (user belongs to group)
- `ASSIGNED_TO` → Application (direct app assignment)
- `ENROLLED` → Factor (MFA enrollment)
- `OWNS` → Device (device ownership)
- `REPORTS_TO` → User (manager relationship)

### OktaGroup
**Purpose:** Represents an Okta group
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `name` (STRING): Group name ⚡ INDEXED
- `source_type` (STRING): AD | LDAP | OKTA_NATIVE | APP_GROUP | BUILT_IN ⚡ INDEXED
- `group_type` (STRING): OKTA_GROUP | BUILT_IN | APP_GROUP ⚡ INDEXED
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `MATCH (g:OktaGroup {name: $name})` - Name lookup
- `WHERE g.source_type = 'AD'` - Source filter
- `WHERE g.group_type = 'OKTA_GROUP'` - Type filter

**Outgoing Relationships:**
- `HAS_ACCESS` → Application (group can access app)

**Incoming Relationships:**
- User → `MEMBER_OF` → OktaGroup

### Application
**Purpose:** Represents an Okta application (SAML or OIDC)
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `label` (STRING): User-visible name (what users see) ⚡ INDEXED
- `name` (STRING): Technical name ⚡ INDEXED
- `status` (STRING): ACTIVE | INACTIVE ⚡ INDEXED
- `sign_on_mode` (STRING): SAML_2_0 | OPENID_CONNECT | SECURE_PASSWORD_STORE | AUTO_LOGIN ⚡ INDEXED
- `policy_id` (STRING): References Policy node ⚡ INDEXED
- `saml_attribute_statements` (STRING[]): SAML attributes (only for SAML apps)
- `oidc_scopes` (STRING[]): OAuth scopes (only for OIDC apps)
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `MATCH (a:Application {label: $label})` - Label lookup
- `MATCH (a:Application {name: $name})` - Name lookup
- `WHERE a.status = 'ACTIVE'` - Status filter
- `WHERE a.sign_on_mode = 'SAML_2_0'` - Protocol filter
- `WHERE a.policy_id = $policy_id` - Policy filter
- `WHERE a.tenant_id = $tenant AND a.status = 'ACTIVE'` - Composite filter

**Outgoing Relationships:**
- `GOVERNED_BY` → Policy (app uses this policy)

**Incoming Relationships:**
- User → `ASSIGNED_TO` → Application (direct assignment)
- OktaGroup → `HAS_ACCESS` → Application (group assignment)

### Policy
**Purpose:** Represents an Okta policy
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `name` (STRING): Policy name ⚡ INDEXED
- `type` (STRING): OKTA_SIGN_ON | PASSWORD | MFA_ENROLL | ACCESS_POLICY ⚡ INDEXED
- `status` (STRING): ACTIVE | INACTIVE ⚡ INDEXED
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `MATCH (p:Policy {name: $name})` - Name lookup
- `WHERE p.type = 'OKTA_SIGN_ON'` - Type filter
- `WHERE p.status = 'ACTIVE'` - Status filter

**Outgoing Relationships:**
- `CONTAINS_RULE` → PolicyRule (policy has rules)

**Incoming Relationships:**
- Application → `GOVERNED_BY` → Policy

### PolicyRule
**Purpose:** Represents a rule within a policy
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `policy_id` (STRING): References Policy ⚡ INDEXED
- `priority` (INT32): Lower = evaluated first
- `access` (STRING): ALLOW | DENY ⚡ INDEXED
- `require_mfa` (BOOLEAN): MFA required? ⚡ INDEXED
- `status` (STRING): ACTIVE | INACTIVE ⚡ INDEXED
- `network_zone_ids` (STRING[]): Network zones for this rule
- `network_zone_names` (STRING[]): Zone names (denormalized for queries)
- `factor_types` (STRING[]): Allowed MFA types
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `WHERE r.policy_id = $policy_id` - Policy filter
- `WHERE r.access = 'ALLOW'` - Access filter
- `WHERE r.require_mfa = true` - MFA filter
- `WHERE r.policy_id = $policy_id AND r.priority <= $priority` - Composite filter

**Outgoing Relationships:**
- `APPLIES_TO_ZONE` → NetworkZone (rule uses zone)
- `APPLIES_TO_USER` → User (rule applies to user)
- `APPLIES_TO_GROUP` → OktaGroup (rule applies to group)

**Incoming Relationships:**
- Policy → `CONTAINS_RULE` → PolicyRule

### Factor
**Purpose:** Represents an MFA factor/authenticator
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `factor_type` (STRING): sms | email | push | token:software:totp | signed_nonce | webauthn ⚡ INDEXED
- `provider` (STRING): OKTA | GOOGLE | DUO | RSA ⚡ INDEXED
- `status` (STRING): ACTIVE | INACTIVE | PENDING_ACTIVATION ⚡ INDEXED
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `WHERE f.factor_type = 'signed_nonce'` - Type filter
- `WHERE f.provider = 'OKTA'` - Provider filter
- `WHERE f.status = 'ACTIVE'` - Status filter

**Incoming Relationships:**
- User → `ENROLLED` → Factor

### Device
**Purpose:** Represents a physical device
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `platform` (STRING): ANDROID | IOS | WINDOWS | MACOS ⚡ INDEXED
- `manufacturer` (STRING): Device manufacturer ⚡ INDEXED
- `status` (STRING): ACTIVE | CREATED | SUSPENDED | DEACTIVATED ⚡ INDEXED
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `WHERE d.platform = 'IOS'` - Platform filter
- `WHERE d.manufacturer = 'Apple'` - Manufacturer filter
- `WHERE d.status = 'ACTIVE'` - Status filter

**Incoming Relationships:**
- User → `OWNS` → Device (with `management_status` property)

### NetworkZone
**Purpose:** Represents IP ranges for policy rules
**Key Properties:**
- `okta_id` (STRING): Unique identifier
- `name` (STRING): Zone name ⚡ INDEXED
- `type` (STRING): IP | DYNAMIC ⚡ INDEXED
- `status` (STRING): ACTIVE | INACTIVE ⚡ INDEXED
- `gateway_ips` (STRING[]): IP addresses
- `tenant_id` (STRING): Tenant identifier ⚡ INDEXED

**Indexed Queries (FAST):**
- `MATCH (z:NetworkZone {name: $name})` - Name lookup
- `WHERE z.type = 'IP'` - Type filter
- `WHERE z.status = 'ACTIVE'` - Status filter

**Incoming Relationships:**
- PolicyRule → `APPLIES_TO_ZONE` → NetworkZone

## Performance Guidelines

### ⚡ FAST Queries (Use Indexed Properties)

**RECOMMENDED - Uses indexes:**
```cypher
# Email lookup (indexed)
MATCH (u:User {email: 'user@example.com'})
RETURN u

# Status filter (indexed)
MATCH (u:User)
WHERE u.status = 'ACTIVE'
RETURN u

# Composite filter (indexed)
MATCH (u:User)
WHERE u.tenant_id = 'trial-8499881' AND u.status = 'ACTIVE'
RETURN u

# Group name lookup (indexed)
MATCH (g:OktaGroup {name: 'sso-super-admins'})
RETURN g

# Application label lookup (indexed)
MATCH (a:Application {label: 'Salesforce'})
WHERE a.status = 'ACTIVE'
RETURN a
```

### 🐌 SLOW Queries (Avoid Unindexed Properties)

**NOT RECOMMENDED - No indexes (table scan):**
```cypher
# First name filter (NOT indexed)
MATCH (u:User)
WHERE u.first_name = 'John'  # ⚠️ SLOW - full table scan
RETURN u

# Mobile phone filter (NOT indexed)
MATCH (u:User)
WHERE u.mobile_phone = '+1234567890'  # ⚠️ SLOW
RETURN u

# Device model filter (NOT indexed)
MATCH (d:Device)
WHERE d.model = 'iPhone 13'  # ⚠️ SLOW
RETURN d
```

**BETTER - Combine with indexed properties:**
```cypher
# Start with indexed property, then filter
MATCH (u:User)
WHERE u.status = 'ACTIVE'  # ⚡ Fast
  AND u.first_name = 'John'  # Then filter in memory
RETURN u

# Or use email if known
MATCH (u:User {email: 'john@example.com'})  # ⚡ Fast
RETURN u
```

### 🎯 Query Optimization Tips

1. **Always filter by tenant_id first** (multi-tenant support)
   ```cypher
   WHERE u.tenant_id = $tenant AND u.status = 'ACTIVE'
   ```

2. **Use indexed properties in MATCH clauses**
   ```cypher
   MATCH (u:User {email: $email})  # ⚡ Fast
   # Better than:
   MATCH (u:User) WHERE u.email = $email  # Slower
   ```

3. **Combine indexed filters for best performance**
   ```cypher
   WHERE a.tenant_id = $tenant 
     AND a.status = 'ACTIVE'
     AND a.sign_on_mode = 'SAML_2_0'
   ```

4. **Filter early in multi-hop queries**
   ```cypher
   # Good - filter users first
   MATCH (u:User {email: $email})-[:MEMBER_OF]->(g:OktaGroup)
   
   # Bad - scan all memberships first
   MATCH (u:User)-[:MEMBER_OF]->(g:OktaGroup)
   WHERE u.email = $email
   ```

5. **Use EXISTS for optional relationship checks**
   ```cypher
   # Find users without MFA
   MATCH (u:User)
   WHERE u.status = 'ACTIVE'
     AND NOT EXISTS { MATCH (u)-[:ENROLLED]->(:Factor) }
   RETURN u
   ```

## Index Coverage Summary

| Node Type | Indexed Properties | Use Case |
|-----------|-------------------|----------|
| **User** | email, login, status, department, user_type, tenant_id, manager | User lookups, status filters, org queries |
| **OktaGroup** | name, source_type, group_type, tenant_id | Group lookups, source filters |
| **Application** | label, name, status, sign_on_mode, policy_id, tenant_id | App lookups, protocol filters |
| **Policy** | name, type, status, tenant_id | Policy lookups, type filters |
| **PolicyRule** | policy_id, access, require_mfa, status, tenant_id | Rule queries, MFA filters |
| **Factor** | factor_type, provider, status, tenant_id | Factor type queries |
| **Device** | platform, manufacturer, status, tenant_id | Device platform queries |
| **NetworkZone** | name, type, status, tenant_id | Zone lookups |

## Composite Indexes

These indexes optimize common multi-property filters:

1. **User (tenant_id, status)** - Most common user filter
2. **Application (tenant_id, status)** - Most common app filter
3. **PolicyRule (policy_id, priority)** - Rule evaluation order

**Usage:**
```cypher
# Automatically uses composite index
MATCH (u:User)
WHERE u.tenant_id = 'trial-8499881' AND u.status = 'ACTIVE'
RETURN u
```

## Query Pattern Examples

### "List apps assigned to user (direct + via groups)"
```cypher
MATCH (u:User {email: $email})
OPTIONAL MATCH (u)-[:ASSIGNED_TO]->(a1:Application)
OPTIONAL MATCH (u)-[:MEMBER_OF]->(g)-[:HAS_ACCESS]->(a2:Application)
WITH collect(a1) + collect(a2) AS apps
UNWIND apps AS app
WHERE app IS NOT NULL
RETURN DISTINCT app.label, app.status
ORDER BY app.label
```

### "Users with MFA factor X"
```cypher
MATCH (u:User)-[:ENROLLED]->(f:Factor {factor_type: $factor_type})
WHERE u.status = 'ACTIVE'
RETURN u.display_name, u.email
ORDER BY u.display_name
```

### "Users in group with no MFA"
```cypher
MATCH (g:OktaGroup {name: $group_name})<-[:MEMBER_OF]-(u:User)
WHERE NOT EXISTS { MATCH (u)-[:ENROLLED]->(:Factor) }
RETURN u.display_name, u.email
ORDER BY u.display_name
```

### "Apps governed by policy X"
```cypher
MATCH (p:Policy {name: $policy_name})<-[:GOVERNED_BY]-(a:Application)
WHERE a.status = 'ACTIVE'
RETURN a.label, a.sign_on_mode
ORDER BY a.label
```

### "Policy rules requiring MFA from specific zone"
```cypher
MATCH (p:Policy {name: $policy_name})-[:CONTAINS_RULE]->(r:PolicyRule)
WHERE r.require_mfa = true
OPTIONAL MATCH (r)-[:APPLIES_TO_ZONE]->(z:NetworkZone)
RETURN r.name, r.priority, collect(z.name) AS zones
ORDER BY r.priority
```

### "Manager's direct reports"
```cypher
MATCH (m:User {email: $manager_email})<-[:REPORTS_TO]-(u:User)
WHERE u.status = 'ACTIVE'
RETURN u.display_name, u.email, u.title
ORDER BY u.display_name
```

### "Devices owned by user"
```cypher
MATCH (u:User {email: $email})-[o:OWNS]->(d:Device)
RETURN d.display_name, d.platform, o.management_status, d.status
ORDER BY d.display_name
```
"""


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

**Core Properties** (26 base properties + dynamic custom attributes):
- okta_id (STRING, PRIMARY KEY) - Unique Okta user identifier (e.g., '00u...')
- email (STRING) - User's primary email address
- login (STRING) - User's login username
- first_name (STRING) - Given name
- last_name (STRING) - Family name
- display_name (STRING) - Full display name
- status (STRING) - User account status (ACTIVE, SUSPENDED, DEPROVISIONED, etc.)
- user_type (STRING) - Type of user account
- title (STRING) - Job title
- department (STRING) - Department name
- organization (STRING) - Organization name
- manager (STRING) - Manager's login username
- employee_number (STRING) - Employee ID
- cost_center (STRING) - Cost center code
- division (STRING) - Division name
- preferred_language (STRING) - Language preference
- locale (STRING) - Locale setting
- timezone (STRING) - Timezone
- mobile_phone (STRING) - Mobile phone number
- primary_phone (STRING) - Primary phone number
- street_address (STRING) - Street address
- city (STRING) - City
- state (STRING) - State/province
- zip_code (STRING) - Postal code
- country_code (STRING) - Country code
- mfa_enrolled (BOOLEAN) - Whether MFA is enrolled

**Dynamic Custom Attributes** (created at sync time from env config):
- custom_attrib_1, custom_attrib_2, custom_attrib_3, custom_attrib_4, custom_attrib_5, testAttrib
- These are dynamically added based on OKTA_USER_CUSTOM_ATTRIBUTES environment variable
- Access them directly: `WHERE u.custom_attrib_1 = 'value'`

**Indexed Properties**: email, login, status, custom_attrib_1

### 2. OktaGroup
Represents an Okta group for organizing users and managing access.

**Properties** (12):
- okta_id (STRING, PRIMARY KEY) - Unique group identifier (e.g., '00g...')
- name (STRING) - Group name
- description (STRING) - Group description
- group_type (STRING) - Type of group (OKTA_GROUP, BUILT_IN, APP_GROUP)
- profile (STRING) - JSON string of additional profile data
- source (STRING) - Source system (Okta, AD, LDAP, etc.)
- source_id (STRING) - External source identifier
- is_managed (BOOLEAN) - Whether group is managed externally
- is_assigned_role (BOOLEAN) - Whether group has admin role assignments
- member_count (INT64) - Number of members in group
- app_count (INT64) - Number of apps assigned to group
- last_membership_updated (STRING) - Last membership change timestamp

**Indexed Properties**: name

### 3. Application
Represents an application integrated with Okta for SSO/authentication.

**Properties** (24):
- okta_id (STRING, PRIMARY KEY) - Unique application identifier (e.g., '0oa...')
- label (STRING) - User-facing application name (what users see)
- name (STRING) - Technical application name
- status (STRING) - Application status (ACTIVE, INACTIVE)
- sign_on_mode (STRING) - Authentication method (SAML_2_0, OPENID_CONNECT, etc.)
- app_type (STRING) - Application type/category
- features (STRING[]) - Array of enabled features
- visibility_auto_submit_toolbar (BOOLEAN) - Auto-submit on toolbar
- visibility_hide_ios (BOOLEAN) - Hide on iOS
- visibility_hide_web (BOOLEAN) - Hide on web
- accessibility_self_service (BOOLEAN) - Self-service enabled
- accessibility_error_redirect_url (STRING) - Error redirect URL
- profile (STRING) - JSON string of app profile data
- settings (STRING) - JSON string of app settings
- credentials_scheme (STRING) - Credential scheme
- credentials_username_template (STRING) - Username template for app
- saml_audience (STRING) - SAML audience URI
- saml_recipient (STRING) - SAML recipient URL
- saml_destination (STRING) - SAML destination URL
- saml_subject_name_id_template (STRING) - SAML name ID template
- saml_subject_name_id_format (STRING) - SAML name ID format
- attribute_statements (STRING[]) - SAML attribute statements (JSON strings)
- created (STRING) - Creation timestamp
- last_updated (STRING) - Last update timestamp

**Indexed Properties**: label, status

### 4. Policy
Represents an Okta authentication or authorization policy.

**Properties** (12):
- okta_id (STRING, PRIMARY KEY) - Unique policy identifier
- name (STRING) - Policy name
- description (STRING) - Policy description
- policy_type (STRING) - Type of policy (OKTA_SIGN_ON, MFA_ENROLL, etc.)
- status (STRING) - Policy status (ACTIVE, INACTIVE)
- priority (INT64) - Policy priority order
- system (BOOLEAN) - Whether system-managed policy
- conditions (STRING) - JSON string of policy conditions
- created (STRING) - Creation timestamp
- last_updated (STRING) - Last update timestamp
- app_count (INT64) - Number of apps using this policy
- rule_count (INT64) - Number of rules in this policy

**Indexed Properties**: name

### 5. PolicyRule
Represents a rule within a policy with specific conditions and actions.

**Properties** (13):
- okta_id (STRING, PRIMARY KEY) - Unique rule identifier
- name (STRING) - Rule name
- status (STRING) - Rule status (ACTIVE, INACTIVE)
- priority (INT64) - Rule priority order
- rule_type (STRING) - Type of rule
- conditions (STRING) - JSON string of rule conditions
- actions (STRING) - JSON string of rule actions
- require_mfa (BOOLEAN) - Whether MFA is required
- allowed_factors (STRING[]) - List of allowed MFA factors
- session_lifetime (INT64) - Session lifetime in minutes
- session_idle (INT64) - Idle timeout in minutes
- created (STRING) - Creation timestamp
- last_updated (STRING) - Last update timestamp

### 6. Factor
Represents an MFA factor/device enrolled by a user.

**Properties** (14):
- okta_id (STRING, PRIMARY KEY) - Unique factor identifier
- factor_type (STRING) - Type of MFA (sms, call, email, push, totp, webauthn, etc.)
- provider (STRING) - MFA provider (OKTA, GOOGLE, RSA, etc.)
- vendor_name (STRING) - Vendor name
- device_type (STRING) - Device type for factor
- status (STRING) - Factor status (ACTIVE, INACTIVE, PENDING_ACTIVATION, etc.)
- profile (STRING) - JSON string of factor profile
- phone_number (STRING) - Phone number for SMS/voice factors
- credential_id (STRING) - Credential identifier
- verification (STRING) - Verification details
- enrolled (STRING) - Enrollment timestamp
- last_verified (STRING) - Last verification timestamp
- last_updated (STRING) - Last update timestamp
- created (STRING) - Creation timestamp

**Indexed Properties**: factor_type

### 7. Device
Represents a device registered with Okta.

**Properties** (16):
- okta_id (STRING, PRIMARY KEY) - Unique device identifier
- device_id (STRING) - Device ID
- status (STRING) - Device status
- platform (STRING) - Platform (IOS, ANDROID, WINDOWS, MACOS, etc.)
- display_name (STRING) - User-friendly device name
- model (STRING) - Device model
- os_version (STRING) - Operating system version
- manufacturer (STRING) - Device manufacturer
- serial_number (STRING) - Device serial number
- imei (STRING) - IMEI number
- meid (STRING) - MEID number
- udid (STRING) - UDID
- sid (STRING) - Security identifier
- registered (STRING) - Registration timestamp
- last_updated (STRING) - Last update timestamp
- profile (STRING) - JSON string of device profile

### 8. NetworkZone
Represents a network zone (IP allowlist/blocklist) in Okta.

**Properties** (10):
- okta_id (STRING, PRIMARY KEY) - Unique zone identifier
- name (STRING) - Zone name
- zone_type (STRING) - Type (IP, DYNAMIC, etc.)
- status (STRING) - Zone status (ACTIVE, INACTIVE)
- usage (STRING) - Usage type (POLICY, BLOCKLIST, etc.)
- gateways (STRING[]) - Array of gateway IPs/CIDRs
- proxies (STRING[]) - Array of proxy IPs/CIDRs
- asns (STRING[]) - Array of ASN numbers
- locations (STRING[]) - Array of geographic locations
- created (STRING) - Creation timestamp

## RELATIONSHIP TYPES (11 total)

### 1. MEMBER_OF
User→OktaGroup: User is a member of a group
**Properties**: None
**Example**: `(u:User)-[:MEMBER_OF]->(g:OktaGroup)`

### 2. HAS_ACCESS
User→Application: User has direct access to an application
**Properties**:
- scope (STRING) - Assignment scope (USER, GROUP)
- assigned_at (STRING) - Assignment timestamp
**Example**: `(u:User)-[:HAS_ACCESS]->(a:Application)`

### 3. GROUP_HAS_ACCESS
OktaGroup→Application: Group has access to an application (group-based assignment)
**Properties**:
- priority (INT64) - Assignment priority
- assigned_at (STRING) - Assignment timestamp
**Example**: `(g:OktaGroup)-[:GROUP_HAS_ACCESS]->(a:Application)`

### 4. ENROLLED
User→Factor: User has enrolled an MFA factor
**Properties**:
- enrolled_at (STRING) - Enrollment timestamp
- last_used (STRING) - Last usage timestamp
**Example**: `(u:User)-[:ENROLLED]->(f:Factor)`

### 5. OWNS
User→Device: User owns a device
**Properties**:
- management_status (STRING) - Device management status
- registered_at (STRING) - Registration timestamp
**Example**: `(u:User)-[:OWNS]->(d:Device)`

### 6. GOVERNED_BY
Application→Policy: Application is governed by a policy
**Properties**: None
**Example**: `(a:Application)-[:GOVERNED_BY]->(p:Policy)`

### 7. CONTAINS_RULE
Policy→PolicyRule: Policy contains a rule
**Properties**: None
**Example**: `(p:Policy)-[:CONTAINS_RULE]->(r:PolicyRule)`

### 8. APPLIES_TO_ZONE
PolicyRule→NetworkZone: Rule applies to a network zone
**Properties**: None
**Example**: `(r:PolicyRule)-[:APPLIES_TO_ZONE]->(z:NetworkZone)`

### 9. APPLIES_TO_USER
PolicyRule→User: Rule applies to specific user
**Properties**: None
**Example**: `(r:PolicyRule)-[:APPLIES_TO_USER]->(u:User)`

### 10. APPLIES_TO_GROUP
PolicyRule→OktaGroup: Rule applies to specific group
**Properties**: None
**Example**: `(r:PolicyRule)-[:APPLIES_TO_GROUP]->(g:OktaGroup)`

### 11. REPORTS_TO
User→User: Manager/report hierarchy
**Properties**: None
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
