"""
Shared Database Schema for SQL Agents
Centralized location for schema information to avoid duplication
"""

def get_okta_database_schema() -> str:
    """Get the complete Okta database schema"""
    
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
            - status (String, INDEX)  # Values: STAGED, PROVISIONED, ACTIVE, PASSWORD_RESET, PASSWORD_EXPIRED, LOCKED_OUT, SUSPENDED, DEPROVISIONED
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
            - sign_on_mode (String, INDEX)  # Values: AUTO_LOGIN, BASIC_AUTH, BOOKMARK, BROWSER_PLUGIN, OPENID_CONNECT, SAML_2_0, WS_FEDERATION
            - metadata_url (String, NULL)
            - policy_id (String, ForeignKey -> policies.okta_id, NULL, INDEX)
            - sign_on_url (String, NULL)
            - audience (String, NULL)
            - destination (String, NULL)
            - signing_kid (String, NULL)
            - username_template (String, NULL) # Template for username generation - Values: BUILT_IN, CUSTOM, NONE
            - username_template_type (String, NULL)  # Template type for username - Use LIKE to search. Format: 'source.attribute' or 'custom.attribute'
            - implicit_assignment (Boolean)
            - admin_note (Text, NULL)
            - attribute_statements (JSON, NULL)  # SAML attribute statements as JSON array - Use LIKE with '{' to search JSON content
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
            - status (String, INDEX)  # Values: ACTIVE, INACTIVE, SUSPENDED, etc.
            - display_name (String, INDEX)  # Device display name
            - platform (String, INDEX)  # Values: ANDROID, iOS, WINDOWS, MACOS, etc.
            - manufacturer (String, INDEX)  # Device manufacturer - Values: samsung, Apple, Dell, HP, Microsoft, etc.
            - model (String)  # Device model
            - os_version (String)  # Operating system version
            - serial_number (String, INDEX)  # Device serial number
            - udid (String, INDEX)  # Unique device identifier
            - registered (Boolean)  # Device registration status
            - secure_hardware_present (Boolean)  # TPM/secure hardware availability
            - disk_encryption_type (String)  # Values: USER, FULL, NONE, etc.
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
            - management_status (String)  # Values: NOT_MANAGED, MANAGED, UNKNOWN, etc.
            - screen_lock_type (String)  # Values: BIOMETRIC, PIN, PASSWORD, PATTERN, NONE, etc.
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
            - factor_type (String, INDEX)  # Values: sms, email, signed_nonce (FastPass/Okta FastPass), password, webauthn (FIDO2), security_question, token:software:totp (TOTP apps), push (Okta Verify)
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
            - status (ENUM: STARTED/SUCCESS/FAILED/ERROR)
            - records_processed (Integer)
            - last_successful_sync (DateTime)
            - error_message (String)
            - created_at (DateTime)
            - updated_at (DateTime)
            INDEXES:
            - idx_sync_tenant_entity (tenant_id, entity_type)
            """
    return schema
