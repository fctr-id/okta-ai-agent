"""
GraphDB Sync Operations

Handles synchronization of Okta data to the graph database.
Replaces SQLite sync operations with graph-based node and edge creation.
"""

import kuzu
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from src.utils.logging import get_logger

logger = get_logger(__name__)


class GraphDBSyncOperations:
    """Handle all GraphDB sync operations for Okta data"""
    
    def __init__(self, db_path: str = "./db/tenant_graph_v1.db"):
        """
        Initialize GraphDB sync operations
        
        Args:
            db_path: Path to the graph database file
        """
        self.db_path = db_path
        self.db: Optional[kuzu.Database] = None
        self.conn: Optional[kuzu.Connection] = None
        self._connect()
        
    def _connect(self):
        """Establish connection to graph database and initialize schema"""
        try:
            # Ensure directory exists
            db_path_obj = Path(self.db_path)
            db_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            self.db = kuzu.Database(self.db_path)
            self.conn = kuzu.Connection(self.db)
            logger.info(f"Connected to GraphDB at: {self.db_path}")
            
            # Initialize schema (idempotent - safe to call multiple times)
            self._initialize_schema()
            
        except Exception as e:
            logger.error(f"Failed to connect to GraphDB: {e}")
            raise
    
    def _initialize_schema(self):
        """Initialize GraphDB schema if not already created"""
        from src.core.okta.graph_db.schema_v2_enhanced import ENHANCED_GRAPH_SCHEMA
        
        logger.info("Initializing GraphDB schema v2 (enhanced)...")
        
        # Remove comments (-- style) and filter out empty lines
        clean_lines = []
        for line in ENHANCED_GRAPH_SCHEMA.split('\n'):
            line = line.strip()
            # Skip comment-only lines and empty lines
            if line.startswith('--') or not line:
                continue
            # Remove inline comments
            if '--' in line:
                line = line.split('--')[0].strip()
            if line:
                clean_lines.append(line)
        
        # Join back and split by semicolons
        clean_schema = ' '.join(clean_lines)
        statements = [s.strip() for s in clean_schema.split(';') if s.strip()]
        
        for statement in statements:
            try:
                self.conn.execute(statement)
            except Exception as e:
                # Ignore "already exists" errors
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    continue
                logger.error(f"Error executing schema statement: {e}")
                # Continue with other statements
        
        logger.info("GraphDB schema ready")
    
    def _ensure_custom_attribute_properties(self, custom_attr_list: List[str]):
        """
        Ensure custom attribute properties exist in User table schema
        
        Kuzu requires properties to be pre-defined before use. This method
        uses ALTER TABLE to add any missing custom attribute properties.
        
        Args:
            custom_attr_list: List of custom attribute names from settings
        """
        for attr_name in custom_attr_list:
            if not attr_name:
                continue
                
            # Sanitize attribute name for Cypher
            safe_attr_name = attr_name.replace('-', '_').replace(' ', '_').replace('.', '_')
            
            try:
                # Try to add the property (will fail silently if it already exists)
                alter_query = f"ALTER TABLE User ADD {safe_attr_name} STRING"
                self.conn.execute(alter_query)
                logger.debug(f"Added custom attribute property: {safe_attr_name}")
            except Exception as e:
                # Ignore "already exists" errors (expected on subsequent batches)
                if "already has property" in str(e).lower() or "already exist" in str(e).lower():
                    continue
                # Log other errors but don't fail
                logger.warning(f"Could not add property {safe_attr_name}: {e}")
    
    def sync_users(self, users: List[Dict[str, Any]], tenant_id: str):
        """
        Sync users to graph database WITH relationships in single pass
        
        Args:
            users: List of user dictionaries from Okta API (includes relationships)
            tenant_id: Tenant identifier for multi-tenancy
        """
        from src.config.settings import settings
        
        logger.info(f"Syncing {len(users)} users with relationships to GraphDB")
        
        # Get custom attribute mapping from environment
        custom_attr_list = settings.okta_user_custom_attributes_list
        
        # Ensure all custom attribute properties exist in schema (one-time per sync)
        if custom_attr_list:
            self._ensure_custom_attribute_properties(custom_attr_list)
        
        synced_count = 0
        error_count = 0
        
        for user in users:
            try:
                # Create display name for graph visualization
                display_name = f"{user.get('first_name', '')} {user.get('last_name', '')}" if user.get('first_name') or user.get('last_name') else user.get('email', user.get('login', 'Unknown'))
                
                # Custom attributes mapping: Use ACTUAL attribute names as properties
                custom_attrs = user.get('custom_attributes', {})
                
                # Get current timestamp for sync metadata
                now = datetime.now(timezone.utc)
                
                # Build dynamic SET clause for ALL custom attributes
                custom_attr_props = {}
                for attr_name in custom_attr_list:
                    if attr_name and attr_name in custom_attrs:
                        # Sanitize attribute name for Cypher (replace special chars)
                        safe_attr_name = attr_name.replace('-', '_').replace(' ', '_').replace('.', '_')
                        custom_attr_props[safe_attr_name] = custom_attrs[attr_name]
                
                # Build dynamic SET clause for custom attributes
                params = {
                    'okta_id': user['okta_id'],
                    'tenant_id': tenant_id,
                    'display_name': display_name.strip(),
                    'email': user.get('email'),
                    'first_name': user.get('first_name'),
                    'last_name': user.get('last_name'),
                    'login': user.get('login'),
                    'status': user.get('status'),
                    'mobile_phone': user.get('mobile_phone'),
                    'primary_phone': user.get('primary_phone'),
                    'employee_number': user.get('employee_number'),
                    'department': user.get('department'),
                    'title': user.get('title'),
                    'organization': user.get('organization'),
                    'manager': user.get('manager'),
                    'user_type': user.get('user_type'),
                    'country_code': user.get('country_code'),
                    'created_at': user.get('created_at'),
                    'last_updated_at': user.get('last_updated_at'),
                    'password_changed_at': user.get('password_changed_at'),
                    'status_changed_at': user.get('status_changed_at'),
                    'last_synced_at': now,
                    'updated_at': now
                }
                
                # Add custom attribute properties to params and build SET clauses
                custom_attr_set_clauses = []
                for safe_attr_name, attr_value in custom_attr_props.items():
                    custom_attr_set_clauses.append(f"u.{safe_attr_name} = ${safe_attr_name}")
                    params[safe_attr_name] = attr_value
                
                # Build complete Cypher query with dynamic custom attributes
                custom_attrs_set = ',\n                        '.join(custom_attr_set_clauses) if custom_attr_set_clauses else ''
                custom_attrs_line = f",\n                        {custom_attrs_set}" if custom_attrs_set else ''
                
                query = f"""
                    MERGE (u:User {{okta_id: $okta_id}})
                    SET u.tenant_id = $tenant_id,
                        u.display_name = $display_name,
                        u.email = $email,
                        u.first_name = $first_name,
                        u.last_name = $last_name,
                        u.login = $login,
                        u.status = $status,
                        u.mobile_phone = $mobile_phone,
                        u.primary_phone = $primary_phone,
                        u.employee_number = $employee_number,
                        u.department = $department,
                        u.title = $title,
                        u.organization = $organization,
                        u.manager = $manager,
                        u.user_type = $user_type,
                        u.country_code = $country_code,
                        u.created_at = $created_at,
                        u.last_updated_at = $last_updated_at,
                        u.password_changed_at = $password_changed_at,
                        u.status_changed_at = $status_changed_at{custom_attrs_line},
                        u.last_synced_at = $last_synced_at,
                        u.updated_at = $updated_at,
                        u.is_deleted = false
                """
                
                # MERGE user node (upsert pattern for idempotency)
                self.conn.execute(query, params)
                
                # Sync relationships immediately (streaming pattern)
                user_id = user['okta_id']
                self._sync_group_memberships(user_id, user.get('group_memberships', []), tenant_id)
                self._sync_app_assignments(user_id, user.get('app_links', []), tenant_id)
                self._sync_factors(user_id, user.get('factors', []), tenant_id)
                
                synced_count += 1
                
            except Exception as e:
                logger.error(f"Error syncing user {user.get('okta_id')}: {e}")
                error_count += 1
        
        logger.info(f"User sync complete: {synced_count} synced, {error_count} errors")
    
    def sync_user_relationships(self, users: List[Dict], tenant_id: str):
        """
        Sync user relationships (groups, apps, factors, devices)
        
        Args:
            users: List of user dictionaries with relationship data
            tenant_id: Tenant identifier
        """
        logger.info(f"Syncing relationships for {len(users)} users")
        
        for user in users:
            user_id = user['okta_id']
            
            # Sync group memberships
            self._sync_group_memberships(user_id, user.get('group_memberships', []), tenant_id)
            
            # Sync app assignments
            self._sync_app_assignments(user_id, user.get('app_links', []), tenant_id)
            
            # Sync factors (MFA)
            self._sync_factors(user_id, user.get('factors', []), tenant_id)
            
            # Sync devices
            self._sync_devices(user_id, user.get('devices', []), tenant_id)
        
        logger.info("User relationship sync complete")
    
    def _sync_group_memberships(self, user_id: str, memberships: List[Dict], tenant_id: str):
        """Sync user-to-group relationships"""
        for membership in memberships:
            try:
                self.conn.execute("""
                    MATCH (u:User {okta_id: $user_id})
                    MATCH (g:OktaGroup {okta_id: $group_id})
                    MERGE (u)-[r:MEMBER_OF]->(g)
                    SET r.tenant_id = $tenant_id,
                        r.assigned_at = $assigned_at
                """, {
                    'user_id': user_id,
                    'group_id': membership['group_okta_id'],
                    'tenant_id': tenant_id,
                    'assigned_at': datetime.now(timezone.utc)
                })
            except Exception as e:
                logger.error(f"Error syncing group membership: {e}")
    
    def _sync_app_assignments(self, user_id: str, app_links: List[Dict], tenant_id: str):
        """Sync user-to-application relationships"""
        for app_link in app_links:
            try:
                self.conn.execute("""
                    MATCH (u:User {okta_id: $user_id})
                    MATCH (a:Application {okta_id: $app_id})
                    MERGE (u)-[r:HAS_ACCESS]->(a)
                    SET r.tenant_id = $tenant_id,
                        r.scope = $scope,
                        r.assigned_at = $assigned_at
                """, {
                    'user_id': user_id,
                    'app_id': app_link['application_okta_id'],
                    'tenant_id': tenant_id,
                    'scope': app_link.get('scope', 'USER'),
                    'assigned_at': datetime.now(timezone.utc)
                })
            except Exception as e:
                logger.error(f"Error syncing app assignment: {e}")
    
    def _sync_factors(self, user_id: str, factors: List[Dict], tenant_id: str):
        """Sync user-to-factor relationships (MFA)"""
        for factor in factors:
            try:
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                # First ensure factor node exists with ALL fields
                self.conn.execute("""
                    MERGE (f:Factor {okta_id: $factor_id})
                    SET f.tenant_id = $tenant_id,
                        f.factor_type = $factor_type,
                        f.provider = $provider,
                        f.vendor_name = $vendor_name,
                        f.authenticator_name = $authenticator_name,
                        f.status = $status,
                        f.device_type = $device_type,
                        f.device_name = $device_name,
                        f.platform = $platform,
                        f.phone_number = $phone_number,
                        f.email = $email,
                        f.created_at = $created_at,
                        f.last_updated_at = $last_updated_at,
                        f.last_synced_at = $last_synced_at,
                        f.is_deleted = false
                """, {
                    'factor_id': factor['okta_id'],
                    'tenant_id': tenant_id,
                    'factor_type': factor.get('factor_type'),
                    'provider': factor.get('provider'),
                    'vendor_name': factor.get('vendor_name'),
                    'authenticator_name': factor.get('authenticator_name'),
                    'status': factor.get('status'),
                    'device_type': factor.get('device_type'),
                    'device_name': factor.get('device_name'),
                    'platform': factor.get('platform'),
                    'phone_number': factor.get('phone_number'),
                    'email': factor.get('email'),
                    'created_at': factor.get('created_at'),
                    'last_updated_at': factor.get('last_updated_at'),
                    'last_synced_at': now
                })
                
                # Then create relationship
                self.conn.execute("""
                    MATCH (u:User {okta_id: $user_id})
                    MATCH (f:Factor {okta_id: $factor_id})
                    MERGE (u)-[r:ENROLLED]->(f)
                    SET r.tenant_id = $tenant_id,
                        r.enrolled_at = $enrolled_at
                """, {
                    'user_id': user_id,
                    'factor_id': factor['okta_id'],
                    'tenant_id': tenant_id,
                    'enrolled_at': factor.get('created_at')
                })
            except Exception as e:
                logger.error(f"Error syncing factor: {e}")
    
    def _sync_devices(self, user_id: str, devices: List[Dict], tenant_id: str):
        """Sync user-to-device relationships"""
        for device in devices:
            try:
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                # First ensure device node exists with ALL fields
                self.conn.execute("""
                    MERGE (d:Device {okta_id: $device_id})
                    SET d.tenant_id = $tenant_id,
                        d.display_name = $display_name,
                        d.serial_number = $serial_number,
                        d.udid = $udid,
                        d.platform = $platform,
                        d.manufacturer = $manufacturer,
                        d.model = $model,
                        d.os_version = $os_version,
                        d.status = $status,
                        d.registered = $registered,
                        d.secure_hardware_present = $secure_hardware_present,
                        d.disk_encryption_type = $disk_encryption_type,
                        d.registered_at = $registered_at,
                        d.created_at = $created_at,
                        d.last_updated_at = $last_updated_at,
                        d.last_synced_at = $last_synced_at,
                        d.is_deleted = false
                """, {
                    'device_id': device['okta_id'],
                    'tenant_id': tenant_id,
                    'display_name': device.get('display_name'),
                    'serial_number': device.get('serial_number'),
                    'udid': device.get('udid'),
                    'platform': device.get('platform'),
                    'manufacturer': device.get('manufacturer'),
                    'model': device.get('model'),
                    'os_version': device.get('os_version'),
                    'status': device.get('status'),
                    'registered': device.get('registered', False),
                    'secure_hardware_present': device.get('secure_hardware_present', False),
                    'disk_encryption_type': device.get('disk_encryption_type'),
                    'registered_at': device.get('registered_at'),
                    'created_at': device.get('created_at'),
                    'last_updated_at': device.get('last_updated_at'),
                    'last_synced_at': now
                })
                
                # Then create relationship with properties
                self.conn.execute("""
                    MATCH (u:User {okta_id: $user_id})
                    MATCH (d:Device {okta_id: $device_id})
                    MERGE (u)-[r:OWNS]->(d)
                    SET r.tenant_id = $tenant_id,
                        r.management_status = $management_status,
                        r.screen_lock_type = $screen_lock_type,
                        r.user_device_created_at = $user_device_created_at,
                        r.created_at = $created_at,
                        r.updated_at = $updated_at
                """, {
                    'user_id': user_id,
                    'device_id': device['okta_id'],
                    'tenant_id': tenant_id,
                    'management_status': device.get('management_status'),
                    'screen_lock_type': device.get('screen_lock_type'),
                    'user_device_created_at': device.get('user_device_created_at'),
                    'created_at': now,
                    'updated_at': now
                })
            except Exception as e:
                logger.error(f"Error syncing device: {e}")
    
    def sync_groups(self, groups: List[Dict], tenant_id: str):
        """
        Sync groups to graph database
        
        Args:
            groups: List of group dictionaries from Okta API
            tenant_id: Tenant identifier
        """
        logger.info(f"Syncing {len(groups)} groups to GraphDB")
        
        synced_count = 0
        error_count = 0
        
        for group in groups:
            try:
                okta_id = group.get('okta_id')
                if not okta_id:
                    logger.error(f"Group missing okta_id, skipping: {group}")
                    error_count += 1
                    continue
                
                # Create display name for visualization
                display_name = group.get('name', 'Unknown Group')
                
                # Determine group source type (if available from API)
                # Default to OKTA_NATIVE if not specified
                source_type = group.get('source_type', 'OKTA_NATIVE')
                group_type = group.get('type', 'OKTA_GROUP')
                
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                self.conn.execute("""
                    MERGE (g:OktaGroup {okta_id: $okta_id})
                    SET g.tenant_id = $tenant_id,
                        g.name = $name,
                        g.description = $description,
                        g.display_name = $display_name,
                        g.source_type = $source_type,
                        g.source_id = $source_id,
                        g.group_type = $group_type,
                        g.created_at = $created_at,
                        g.last_updated_at = $last_updated_at,
                        g.last_synced_at = $last_synced_at,
                        g.updated_at = $updated_at,
                        g.is_deleted = false
                """, {
                    'okta_id': okta_id,
                    'tenant_id': tenant_id,
                    'name': group.get('name'),
                    'description': group.get('description'),
                    'display_name': display_name,
                    'source_type': source_type,
                    'source_id': group.get('source_id'),
                    'group_type': group_type,
                    'created_at': group.get('created_at'),
                    'last_updated_at': group.get('last_updated_at'),
                    'last_synced_at': now,
                    'updated_at': now
                })
                synced_count += 1
            except Exception as e:
                logger.error(f"Error syncing group {group.get('okta_id')}: {e}")
                error_count += 1
                
        logger.info(f"Group sync complete: {synced_count} synced, {error_count} errors")
    
    def sync_applications(self, apps: List[Dict], tenant_id: str):
        """
        Sync applications and group assignments
        
        Args:
            apps: List of application dictionaries from Okta API
            tenant_id: Tenant identifier
        """
        logger.info(f"Syncing {len(apps)} applications to GraphDB")
        
        synced_count = 0
        error_count = 0
        
        for app in apps:
            try:
                # Create display name for visualization
                display_name = app.get('label') or app.get('name', 'Unknown App')
                
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                # Convert attribute_statements to STRING[] for GraphDB
                # attribute_statements from Okta is a list of STRUCT objects, we need to convert to strings
                attribute_statements = app.get('attribute_statements', [])
                if attribute_statements:
                    # Convert each statement object to JSON string
                    import json
                    if isinstance(attribute_statements, list):
                        # Convert list of dicts to list of JSON strings
                        attribute_statements = [json.dumps(stmt) if isinstance(stmt, dict) else str(stmt) for stmt in attribute_statements]
                    elif isinstance(attribute_statements, dict):
                        # Single dict - convert to list with one JSON string
                        attribute_statements = [json.dumps(attribute_statements)]
                    else:
                        # Fallback - convert to string and wrap in list
                        attribute_statements = [str(attribute_statements)]
                else:
                    attribute_statements = []
                
                # Sync app node with ALL fields from models.py
                self.conn.execute("""
                    MERGE (a:Application {okta_id: $okta_id})
                    SET a.tenant_id = $tenant_id,
                        a.name = $name,
                        a.label = $label,
                        a.display_name = $display_name,
                        a.status = $status,
                        a.sign_on_mode = $sign_on_mode,
                        a.metadata_url = $metadata_url,
                        a.sign_on_url = $sign_on_url,
                        a.audience = $audience,
                        a.destination = $destination,
                        a.signing_kid = $signing_kid,
                        a.username_template = $username_template,
                        a.username_template_type = $username_template_type,
                        a.implicit_assignment = $implicit_assignment,
                        a.admin_note = $admin_note,
                        a.attribute_statements = $attribute_statements,
                        a.honor_force_authn = $honor_force_authn,
                        a.hide_ios = $hide_ios,
                        a.hide_web = $hide_web,
                        a.policy_id = $policy_id,
                        a.created_at = $created_at,
                        a.last_updated_at = $last_updated_at,
                        a.last_synced_at = $last_synced_at,
                        a.updated_at = $updated_at,
                        a.is_deleted = false
                """, {
                    'okta_id': app['okta_id'],
                    'tenant_id': tenant_id,
                    'name': app.get('name'),
                    'label': app.get('label'),
                    'display_name': display_name,
                    'status': app.get('status'),
                    'sign_on_mode': app.get('sign_on_mode'),
                    'metadata_url': app.get('metadata_url'),
                    'sign_on_url': app.get('sign_on_url'),
                    'audience': app.get('audience'),
                    'destination': app.get('destination'),
                    'signing_kid': app.get('signing_kid'),
                    'username_template': app.get('username_template'),
                    'username_template_type': app.get('username_template_type'),
                    'implicit_assignment': app.get('implicit_assignment', False),
                    'admin_note': app.get('admin_note'),
                    'attribute_statements': attribute_statements,
                    'honor_force_authn': app.get('honor_force_authn', False),
                    'hide_ios': app.get('hide_ios', False),
                    'hide_web': app.get('hide_web', False),
                    'policy_id': app.get('policy_id'),
                    'created_at': app.get('created_at'),
                    'last_updated_at': app.get('last_updated_at'),
                    'last_synced_at': now,
                    'updated_at': now
                })
                
                # Sync group assignments
                for group_assignment in app.get('app_group_assignments', []):
                    try:
                        self.conn.execute("""
                            MATCH (g:OktaGroup {okta_id: $group_id})
                            MATCH (a:Application {okta_id: $app_id})
                            MERGE (g)-[r:GROUP_HAS_ACCESS]->(a)
                            SET r.tenant_id = $tenant_id,
                                r.priority = $priority,
                                r.assigned_at = $assigned_at
                        """, {
                            'group_id': group_assignment['group_okta_id'],
                            'app_id': app['okta_id'],
                            'tenant_id': tenant_id,
                            'priority': group_assignment.get('priority', 0),
                            'assigned_at': datetime.now(timezone.utc)
                        })
                    except Exception as e:
                        logger.error(f"Error syncing group assignment: {e}")
                
                synced_count += 1
                        
            except Exception as e:
                logger.error(f"Error syncing application {app.get('okta_id')}: {e}")
                error_count += 1
                
        logger.info(f"Application sync complete: {synced_count} synced, {error_count} errors")
    
    def sync_policies(self, policies: List[Dict], tenant_id: str):
        """
        Sync policies to graph database
        
        Args:
            policies: List of policy dictionaries from Okta API
            tenant_id: Tenant identifier for multi-tenancy
        """
        logger.info(f"Syncing {len(policies)} policies to GraphDB")
        
        synced_count = 0
        error_count = 0
        
        for policy in policies:
            try:
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                # Create/update policy node
                self.conn.execute("""
                    MERGE (p:Policy {okta_id: $okta_id})
                    SET p.tenant_id = $tenant_id,
                        p.name = $name,
                        p.description = $description,
                        p.type = $type,
                        p.status = $status,
                        p.priority = $priority,
                        p.system = $system,
                        p.created_at = $created_at,
                        p.last_updated_at = $last_updated_at,
                        p.last_synced_at = $last_synced_at,
                        p.is_deleted = false
                """, {
                    'okta_id': policy['okta_id'],
                    'tenant_id': tenant_id,
                    'name': policy.get('name'),
                    'description': policy.get('description'),
                    'type': policy.get('type'),
                    'status': policy.get('status'),
                    'priority': policy.get('priority'),
                    'system': policy.get('system', False),
                    'created_at': policy.get('created_at'),
                    'last_updated_at': policy.get('last_updated_at'),
                    'last_synced_at': now
                })
                
                synced_count += 1
                
            except Exception as e:
                logger.error(f"Error syncing policy {policy.get('okta_id')}: {e}")
                error_count += 1
        
        logger.info(f"Policy sync complete: {synced_count} synced, {error_count} errors")
    
    def sync_devices(self, devices: List[Dict], tenant_id: str):
        """
        Sync devices to graph database with user relationships
        
        Args:
            devices: List of device dictionaries from Okta API (with embedded user relationships)
            tenant_id: Tenant identifier for multi-tenancy
        """
        logger.info(f"Syncing {len(devices)} devices to GraphDB")
        
        synced_count = 0
        error_count = 0
        
        for device in devices:
            try:
                # Get current timestamp
                now = datetime.now(timezone.utc)
                
                # Create/update device node
                self.conn.execute("""
                    MERGE (d:Device {okta_id: $okta_id})
                    SET d.tenant_id = $tenant_id,
                        d.status = $status,
                        d.display_name = $display_name,
                        d.platform = $platform,
                        d.manufacturer = $manufacturer,
                        d.model = $model,
                        d.os_version = $os_version,
                        d.serial_number = $serial_number,
                        d.udid = $udid,
                        d.registered = $registered,
                        d.secure_hardware_present = $secure_hardware_present,
                        d.disk_encryption_type = $disk_encryption_type,
                        d.created_at = $created_at,
                        d.last_updated_at = $last_updated_at,
                        d.last_synced_at = $last_synced_at,
                        d.is_deleted = false
                """, {
                    'okta_id': device['okta_id'],
                    'tenant_id': tenant_id,
                    'status': device.get('status'),
                    'display_name': device.get('display_name'),
                    'platform': device.get('platform'),
                    'manufacturer': device.get('manufacturer'),
                    'model': device.get('model'),
                    'os_version': device.get('os_version'),
                    'serial_number': device.get('serial_number'),
                    'udid': device.get('udid'),
                    'registered': device.get('registered', False),
                    'secure_hardware_present': device.get('secure_hardware_present', False),
                    'disk_encryption_type': device.get('disk_encryption_type'),
                    'created_at': device.get('created_at'),
                    'last_updated_at': device.get('last_updated_at'),
                    'last_synced_at': now
                })
                
                # Sync device-to-user relationships (from embedded users)
                device_users = device.get('device_users', [])
                for user_relation in device_users:
                    try:
                        self.conn.execute("""
                            MATCH (u:User {okta_id: $user_id})
                            MATCH (d:Device {okta_id: $device_id})
                            MERGE (u)-[r:OWNS]->(d)
                            SET r.tenant_id = $tenant_id,
                                r.managed = $managed,
                                r.assigned_at = $assigned_at
                        """, {
                            'user_id': user_relation['user_okta_id'],
                            'device_id': device['okta_id'],
                            'tenant_id': tenant_id,
                            'managed': user_relation.get('managementStatus') == 'MANAGED',
                            'assigned_at': datetime.now(timezone.utc)
                        })
                    except Exception as e:
                        logger.error(f"Error syncing device-user relationship: {e}")
                
                synced_count += 1
                
            except Exception as e:
                logger.error(f"Error syncing device {device.get('okta_id')}: {e}")
                error_count += 1
        
        logger.info(f"Device sync complete: {synced_count} synced, {error_count} errors")
    
    def get_entity_counts(self, tenant_id: str) -> Dict[str, int]:
        """
        Get counts of all entities for sync reporting
        
        Args:
            tenant_id: Tenant identifier
            
        Returns:
            Dictionary with entity counts
        """
        counts = {}
        
        try:
            # Count users
            result = self.conn.execute("""
                MATCH (u:User)
                WHERE u.tenant_id = $tenant_id
                RETURN COUNT(u) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['users'] = int(row[0]) if row else 0
            
            # Count groups
            result = self.conn.execute("""
                MATCH (g:OktaGroup)
                WHERE g.tenant_id = $tenant_id
                RETURN COUNT(g) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['groups'] = int(row[0]) if row else 0
            
            # Count applications
            result = self.conn.execute("""
                MATCH (a:Application)
                WHERE a.tenant_id = $tenant_id
                RETURN COUNT(a) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['apps'] = int(row[0]) if row else 0
            
            # Count factors
            result = self.conn.execute("""
                MATCH (f:Factor)
                WHERE f.tenant_id = $tenant_id
                RETURN COUNT(f) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['factors'] = int(row[0]) if row else 0
            
            # Count devices
            result = self.conn.execute("""
                MATCH (d:Device)
                WHERE d.tenant_id = $tenant_id
                RETURN COUNT(d) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['devices'] = int(row[0]) if row else 0
            
            # Count policies
            result = self.conn.execute("""
                MATCH (p:Policy)
                WHERE p.tenant_id = $tenant_id
                RETURN COUNT(p) as count
            """, {'tenant_id': tenant_id})
            row = result.get_next()
            counts['policies'] = int(row[0]) if row else 0
            
        except Exception as e:
            logger.error(f"Error getting entity counts: {e}")
        
        return counts
    
    def cleanup_old_data(self, tenant_id: str):
        """
        Clean all data for a tenant (for fresh sync)
        
        Args:
            tenant_id: Tenant identifier
        """
        logger.info(f"Cleaning GraphDB data for tenant: {tenant_id}")
        
        try:
            # Delete all relationships first (must use directed pattern in Kuzu)
            for rel_type in ['MEMBER_OF', 'HAS_ACCESS', 'ENROLLED', 'OWNS', 'GROUP_HAS_ACCESS', 'GOVERNED_BY']:
                self.conn.execute(f"""
                    MATCH ()-[r:{rel_type}]->()
                    WHERE r.tenant_id = $tenant_id
                    DELETE r
                """, {'tenant_id': tenant_id})
            
            # Then delete nodes
            for node_type in ['User', 'OktaGroup', 'Application', 'Factor', 'Device', 'Policy']:
                self.conn.execute(f"""
                    MATCH (n:{node_type})
                    WHERE n.tenant_id = $tenant_id
                    DELETE n
                """, {'tenant_id': tenant_id})
            
            logger.info("Cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn = None
        if self.db:
            self.db = None
        logger.info("GraphDB connection closed")
