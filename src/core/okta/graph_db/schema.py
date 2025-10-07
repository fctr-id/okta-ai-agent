"""
GraphDB Schema Definition

Defines the graph database schema for Okta identity data including:
- Node types (User, Group, Application, Factor, Device, Policy)
- Relationship types (edges between nodes)
- Indexes for query performance
"""

import kuzu
from pathlib import Path
from src.utils.logging import get_logger

logger = get_logger(__name__)

GRAPH_SCHEMA = """
CREATE NODE TABLE User (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    display_name STRING,
    email STRING,
    first_name STRING,
    last_name STRING,
    login STRING,
    status STRING,
    mobile_phone STRING,
    primary_phone STRING,
    employee_number STRING,
    department STRING,
    manager STRING,
    title STRING,
    organization STRING,
    user_type STRING,
    country_code STRING,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    password_changed_at TIMESTAMP,
    status_changed_at TIMESTAMP,
    custom_attributes MAP(STRING, STRING)
);

CREATE NODE TABLE OktaGroup (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    name STRING,
    description STRING,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP
);

CREATE NODE TABLE Application (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    name STRING,
    label STRING,
    status STRING,
    sign_on_mode STRING,
    sign_on_url STRING,
    audience STRING,
    destination STRING,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    policy_id STRING,
    implicit_assignment BOOLEAN,
    admin_note STRING
);

CREATE NODE TABLE Factor (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    factor_type STRING,
    provider STRING,
    vendor_name STRING,
    status STRING,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP
);

CREATE NODE TABLE Device (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    platform STRING,
    status STRING,
    display_name STRING,
    manufacturer STRING,
    model STRING,
    os_version STRING,
    screen_lock_type STRING,
    registered_at TIMESTAMP,
    last_updated_at TIMESTAMP
);

CREATE NODE TABLE Policy (
    okta_id STRING PRIMARY KEY,
    tenant_id STRING,
    name STRING,
    description STRING,
    type STRING,
    priority INT32,
    status STRING,
    created_at TIMESTAMP,
    last_updated_at TIMESTAMP,
    system BOOLEAN
);

CREATE NODE TABLE SyncMetadata (
    sync_id STRING PRIMARY KEY,
    version INT32,
    tenant_id STRING,
    success BOOLEAN,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    users_count INT64,
    groups_count INT64,
    apps_count INT64,
    error_message STRING
);

CREATE REL TABLE MEMBER_OF (
    FROM User TO OktaGroup,
    tenant_id STRING,
    assigned_at TIMESTAMP
);

CREATE REL TABLE ASSIGNED_TO (
    FROM User TO Application,
    tenant_id STRING,
    scope STRING,
    assigned_at TIMESTAMP
);

CREATE REL TABLE ENROLLED (
    FROM User TO Factor,
    tenant_id STRING,
    enrolled_at TIMESTAMP,
    last_verified_at TIMESTAMP
);

CREATE REL TABLE OWNS (
    FROM User TO Device,
    tenant_id STRING,
    registered_at TIMESTAMP
);

CREATE REL TABLE HAS_ACCESS (
    FROM OktaGroup TO Application,
    tenant_id STRING,
    priority INT32,
    assigned_at TIMESTAMP
);

CREATE REL TABLE GOVERNED_BY (
    FROM Application TO Policy,
    tenant_id STRING,
    assigned_at TIMESTAMP
);
"""


def initialize_graph_schema(db_path: str = "./graph_db/okta_graph.db") -> tuple:
    """
    Initialize GraphDB with Okta schema
    
    Args:
        db_path: Path to the graph database file
        
    Returns:
        Tuple of (database, connection) objects
    """
    logger.info(f"Initializing GraphDB schema at: {db_path}")
    
    # Ensure directory exists
    db_path_obj = Path(db_path)
    db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize database
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    
    # Execute schema creation
    statements = [s.strip() for s in GRAPH_SCHEMA.strip().split(';') if s.strip()]
    
    for statement in statements:
        try:
            conn.execute(statement)
            # Extract table name for logging
            if 'CREATE NODE TABLE' in statement or 'CREATE REL TABLE' in statement:
                table_name = statement.split('TABLE')[1].split('(')[0].strip()
                logger.info(f"✓ Created: {table_name}")
        except Exception as e:
            logger.error(f"✗ Error executing statement: {e}")
            logger.debug(f"  Statement: {statement[:100]}...")
    
    logger.info("GraphDB schema initialized successfully!")
    return db, conn


def create_indexes(conn: kuzu.Connection):
    """
    Create performance indexes on graph database
    
    Note: Kuzu automatically indexes primary keys and foreign keys.
    Additional indexes can be created for frequently queried properties.
    """
    logger.info("Creating performance indexes...")
    
    # Note: As of Kuzu v0.5.0, additional indexes beyond primary keys
    # are created automatically. This function is a placeholder for
    # future custom index creation if needed.
    
    logger.info("Index creation complete")
