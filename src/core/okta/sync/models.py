from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Table, Index, UniqueConstraint, Text, JSON, Enum as SQLEnum
from sqlalchemy.sql import func, text, functions
from datetime import datetime, timezone
import enum

Base = declarative_base()

# Add this helper function at the top of the file
def get_utc_now():
    """Return current UTC datetime"""
    return datetime.now(timezone.utc)

# ========================================================================
# BASE CLASSES - COMMENTED OUT FOR GRAPHDB MODE
# These abstract base classes are only used by business data models.
# When using GraphDB mode, business data is in Kuzu, not SQLite.
# ========================================================================

# class BaseModel(Base):
#     __abstract__ = True
#     
#     id = Column(Integer, primary_key=True)
#     tenant_id = Column(String, nullable=False, index=True)
#     okta_id = Column(String, nullable=False, index=True)
#     # API response timestamps
#     created_at = Column(DateTime(timezone=True), nullable=True)
#     last_updated_at = Column(DateTime(timezone=True), nullable=True)
#     
#     # Local tracking timestamps
#     last_synced_at = Column(DateTime(timezone=True), index=True)
#     updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)
#     is_deleted = Column(Boolean, default=False, index=True)
# 
#     __table_args__ = (
#         UniqueConstraint('tenant_id', 'okta_id', name='uix_tenant_okta_id'),
#         Index('idx_tenant_deleted', 'tenant_id', 'is_deleted')
#     )
# 
# class SyncBase(Base):
#     __abstract__ = True
#     
#     id = Column(Integer, primary_key=True)
#     tenant_id = Column(String, nullable=False, index=True)
#     created_at = Column(DateTime(timezone=True), default=get_utc_now)
#     updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)   

#user_groups = Table(
#    'user_groups',
#    Base.metadata,
#    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
#    Column('group_id', Integer, ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True),
#    Column('tenant_id', String, nullable=False, index=True),
#    Column('created_at', DateTime, default=datetime.utcnow),
#    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
#    Index('idx_user_groups_tenant', 'tenant_id')
#)

#user_authenticators = Table(
#    'user_authenticators',
#    Base.metadata,
#    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
#    Column('authenticator_id', Integer, ForeignKey('authenticators.id', ondelete='CASCADE'), primary_key=True),
#    Column('tenant_id', String, nullable=False, index=True),
#    Column('created_at', DateTime, default=datetime.utcnow),
#    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
#    Index('idx_user_auth_tenant', 'tenant_id')
#)

# ========================================================================
# BUSINESS DATA MODELS - COMMENTED OUT FOR GRAPHDB MODE
# These tables are only needed when using SQLite for business data storage.
# When using GraphDB mode, all business data is stored in Kuzu GraphDB.
# Only metadata models (SyncHistory, AuthUser) are needed in SQLite.
# ========================================================================

# # Direct user-application assignments
# user_application_assignments = Table(
#     'user_application_assignments',
#     Base.metadata,
#     Column('user_okta_id', String, ForeignKey('users.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('application_okta_id', String, ForeignKey('applications.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('tenant_id', String, nullable=False),
#     Column('assignment_id', String, nullable=False),  # appAssignmentId from appLinks
#     Column('app_instance_id', String, nullable=False),  # appInstanceId from appLinks
#     Column('credentials_setup', Boolean, default=False),
#     Column('hidden', Boolean, default=False),
#     Column('created_at', DateTime(timezone=True), default=get_utc_now),
#     Column('updated_at', DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now),
#     Index('idx_user_app_tenant', 'tenant_id'),
#     Index('idx_uaa_application', 'tenant_id', 'application_okta_id'),
#     UniqueConstraint('tenant_id', 'user_okta_id', 'application_okta_id', name='uix_user_app_assignment')
# )

# # Group-application assignments
# group_application_assignments = Table(
#     'group_application_assignments',
#     Base.metadata,
#     Column('group_okta_id', String, ForeignKey('groups.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('application_okta_id', String, ForeignKey('applications.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('tenant_id', String, nullable=False),
#     Column('assignment_id', String, nullable=False),
#     Column('created_at', DateTime(timezone=True), default=get_utc_now),
#     Column('updated_at', DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now),
#     Index('idx_group_app_tenant', 'tenant_id'),
#     Index('idx_gaa_application', 'tenant_id', 'application_okta_id'),
#     UniqueConstraint('tenant_id', 'group_okta_id', 'application_okta_id', name='uix_group_app_assignment')
# )

# # User-group memberships
# user_group_memberships = Table(
#     'user_group_memberships',
#     Base.metadata,
#     Column('user_okta_id', String, ForeignKey('users.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('group_okta_id', String, ForeignKey('groups.okta_id', ondelete='CASCADE'), primary_key=True),
#     Column('tenant_id', String, nullable=False),
#     Column('created_at', DateTime(timezone=True), default=get_utc_now),
#     Column('updated_at', DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now),
#     Index('idx_user_group_tenant', 'tenant_id'),
#     Index('idx_user_by_group', 'tenant_id', 'group_okta_id'),
#     UniqueConstraint('tenant_id', 'user_okta_id', 'group_okta_id', name='uix_user_group_membership')
# )

# class User(BaseModel):
#     __tablename__ = 'users'
#     
#     email = Column(String, index=True)
#     first_name = Column(String)
#     last_name = Column(String)
#     login = Column(String, index=True)
#     status = Column(String, index=True)
#     mobile_phone = Column(String)
#     primary_phone = Column(String)
#     employee_number = Column(String, index=True)
#     department = Column(String, index=True)
#     manager = Column(String) 
#     password_changed_at = Column(DateTime(timezone=True), nullable=True)
#     status_changed_at = Column(DateTime(timezone=True), nullable=True, index=True)  
#     user_type = Column(String, nullable=True)
#     country_code = Column(String, nullable=True, index=True)
#     title = Column(String, nullable=True)
#     organization = Column(String, nullable=True, index=True)
#     
#     #JSON column for custom attributes from env variables
#     custom_attributes = Column(JSON, nullable=True, default={})
#     
#     
#     #groups = relationship('Group', secondary=user_groups, back_populates='users', passive_deletes=True)
#     #authenticators = relationship('Authenticator', secondary=user_authenticators, back_populates='users', passive_deletes=True)
#     # Direct application assignments
#     direct_applications = relationship('Application',secondary=user_application_assignments,back_populates='direct_users',passive_deletes=True)
#     # Group memberships
#     groups = relationship('Group',secondary=user_group_memberships,back_populates='users',passive_deletes=True)
#     factors = relationship('UserFactor', back_populates='user', cascade='all, delete-orphan')
#     devices = relationship('UserDevice', foreign_keys='UserDevice.user_okta_id', back_populates='user', cascade='all, delete-orphan')
#     
#     __table_args__ = (
#         Index('idx_user_tenant_email', 'tenant_id', 'email'),
#         Index('idx_user_tenant_login', 'tenant_id', 'login'),
#         Index('idx_user_employee_number', 'tenant_id', 'employee_number'),
#         Index('idx_user_department', 'tenant_id', 'department'),
#         Index('idx_user_country_code', 'tenant_id', 'country_code'),
#         Index('idx_user_organization', 'tenant_id', 'organization'),
#         Index('idx_user_manager', 'tenant_id', 'manager'),
#         Index('idx_user_name_search', 'tenant_id', 'first_name', 'last_name'),
#         Index('idx_user_status_filter', 'tenant_id', 'status', 'is_deleted'),
#         Index('idx_user_status_changed', 'tenant_id', 'status_changed_at'),
#         {'extend_existing': True}
#     )

# class Group(BaseModel):
#     __tablename__ = 'groups'
#     
#     name = Column(String, index=True)
#     description = Column(String)
#     
#     # User memberships
#     users = relationship('User',secondary=user_group_memberships,back_populates='groups',passive_deletes=True)
#     
#     # Application assignments
#     applications = relationship('Application',secondary=group_application_assignments,back_populates='assigned_groups',passive_deletes=True)
# 
# 
#     __table_args__ = (
#         Index('idx_group_tenant_name', 'tenant_id', 'name'),
#         {'extend_existing': True}
#     )

# class Authenticator(BaseModel):
#     __tablename__ = 'authenticators'
#     
#     name = Column(String, index=True)
#     status = Column(String, index=True)
#     type = Column(String, index=True)
#     
#     #users = relationship('User', secondary=user_authenticators, back_populates='authenticators', passive_deletes=True)
# 
#     __table_args__ = (
#         Index('idx_auth_tenant_name', 'tenant_id', 'name'),
#         {'extend_existing': True}
#     )

# class Application(BaseModel):
#     __tablename__ = 'applications'
#     
#     # Required fields
#     okta_id = Column(String, nullable=False, index=True)
#     name = Column(String, index=True)
#     label = Column(String)
#     status = Column(String, index=True)
#     sign_on_mode = Column(String, index=True)
#     
#     # URLs and Integration
#     metadata_url = Column(String, nullable=True)
#     policy_id = Column(String, ForeignKey('policies.okta_id', ondelete='SET NULL'), nullable=True, index=True)
#     sign_on_url = Column(String, nullable=True)
#     audience = Column(String, nullable=True)
#     destination = Column(String, nullable=True)
#     
#     # Authentication
#     signing_kid = Column(String, nullable=True)
#     username_template = Column(String, nullable=True)
#     username_template_type = Column(String, nullable=True)
#     
#     # Settings
#     implicit_assignment = Column(Boolean, default=False)
#     admin_note = Column(Text, nullable=True)
#     
#     # SAML Settings
#     attribute_statements = Column(JSON, nullable=True, default=[])
#     honor_force_authn = Column(Boolean, default=False)
#     
#     # Visibility
#     hide_ios = Column(Boolean, default=False)
#     hide_web = Column(Boolean, default=False)
#     
#     # Timestamps and flags
#     created_at = Column(DateTime(timezone=True), nullable=True)
#     last_updated_at = Column(DateTime(timezone=True), nullable=True)
#     last_synced_at = Column(DateTime(timezone=True), nullable=True)
#     
#     # Relationships
#     policy = relationship('Policy', foreign_keys=[policy_id], back_populates='applications')
#     # Direct user assignments
#     direct_users = relationship('User',secondary=user_application_assignments,back_populates='direct_applications',passive_deletes=True)
#     
#     # Group assignments
#     assigned_groups = relationship('Group',secondary=group_application_assignments,back_populates='applications',passive_deletes=True)
# 
#     #__table_args__ = (
#     #    Index('idx_app_tenant_name', 'tenant_id', 'name'),
#     #    {'extend_existing': True}
#     #)
# 
#     __table_args__ = (
#         Index('idx_app_tenant_name', 'tenant_id', 'name'),
#         Index('idx_app_okta_id', 'okta_id'),
#         Index('idx_app_status', 'status'),
#         Index('idx_app_sign_on_mode', 'sign_on_mode'),
#         Index('idx_app_policy', 'policy_id'),
#         Index('idx_app_label', 'label'),
#         Index('idx_app_attrs', 'attribute_statements', sqlite_where=text("json_valid(attribute_statements)")),
#         {'extend_existing': True}
#     )
#      

# class PolicyType(enum.Enum):
#     OKTA_SIGN_ON = "OKTA_SIGN_ON"
#     PASSWORD = "PASSWORD"
#     MFA_ENROLL = "MFA_ENROLL"
#     IDP_DISCOVERY = "IDP_DISCOVERY"
#     ACCESS_POLICY = "ACCESS_POLICY"
#     PROFILE_ENROLLMENT = "PROFILE_ENROLLMENT"
#     POST_AUTH_SESSION = "POST_AUTH_SESSION"
#     ENTITY_RISK = "ENTITY_RISK"
#     
# class Policy(BaseModel):
#     __tablename__ = 'policies'
#     
#     okta_id = Column(String, nullable=False, index=True)
#     name = Column(String, index=True)
#     description = Column(String, nullable=True)
#     status = Column(String, index=True)
#     type = Column(String, index=True)
#     
#     # Timestamps
#     created_at = Column(DateTime(timezone=True), nullable=True)
#     last_updated_at = Column(DateTime(timezone=True), nullable=True)
#     last_synced_at = Column(DateTime(timezone=True), nullable=True)
#     
#     # Relationships
#     applications = relationship('Application', back_populates='policy', foreign_keys='Application.policy_id')
# 
#     __table_args__ = (
#         Index('idx_policy_tenant_name', 'tenant_id', 'name'),
#         Index('idx_policy_okta_id', 'okta_id'),
#         Index('idx_policy_type', 'type'),
#         {'extend_existing': True}
#     )
#     
# class FactorType(enum.Enum):
#     SMS = "sms"
#     EMAIL = "email"
#     CALL = "call"
#     PUSH = "push"
#     TOTP = "token:software:totp"
#     HOTP = "token:software:hotp"
#     HARDWARE = "token:hardware"
#     SECURITY_QUESTION = "question"
#     WEBAUTHN = "webauthn"    
#     FASTPASS = "signed_nonce"
#     
# class UserFactor(BaseModel):
#     __tablename__ = 'user_factors'
#     
#     okta_id = Column(String, index=True, nullable=False)
#     user_okta_id = Column(String, ForeignKey('users.okta_id', ondelete='CASCADE'))
#     factor_type = Column(String, index=True)
#     provider = Column(String, index=True)
#     status = Column(String, index=True)
#     
#     authenticator_name = Column(String, nullable=True, index=True)
# 
#     
#     # New timestamp fields
#     created_at = Column(DateTime(timezone=True), nullable=True)
#     last_updated_at = Column(DateTime(timezone=True), nullable=True)
#     
#     # Factor type specific fields
#     email = Column(String, nullable=True)
#     phone_number = Column(String, nullable=True)
#     device_type = Column(String, nullable=True)
#     device_name = Column(String, nullable=True)
#     platform = Column(String, nullable=True)
#     
#     user = relationship('User', 
#                        foreign_keys=[user_okta_id],
#                        primaryjoin="and_(UserFactor.user_okta_id==User.okta_id, "
#                                  "UserFactor.tenant_id==User.tenant_id)")
# 
#     __table_args__ = (
#         Index('idx_factor_tenant_user', 'tenant_id', 'user_okta_id'),
#         Index('idx_factor_okta_id', 'okta_id'),
#         Index('idx_factor_type_status', 'factor_type', 'status'),
#         Index('idx_factor_provider_status', 'provider', 'status'),
#         Index('idx_factor_tenant_user_type', 'tenant_id', 'user_okta_id', 'factor_type'),
#         Index('idx_tenant_factor_type', 'tenant_id', 'factor_type'),
#         UniqueConstraint('tenant_id', 'user_okta_id', 'okta_id', 
#                         name='uix_factor_tenant_user_okta'),
#         {'extend_existing': True}
#     )
#     
# ========================================================================
# END OF COMMENTED OUT BUSINESS DATA MODELS
# ========================================================================

# Create stub/placeholder classes for backward compatibility
# These allow imports to work but prevent table creation
# Real business data is stored in GraphDB, not SQLite
class _StubModel:
    """Stub class to allow imports but prevent instantiation"""
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "Business data models are disabled in GraphDB mode. "
            "Data is stored in Kuzu GraphDB, not SQLite tables."
        )

# Stub classes for business models
User = _StubModel
Group = _StubModel  
Application = _StubModel
Policy = _StubModel
Authenticator = _StubModel
UserFactor = _StubModel
Device = _StubModel
UserDevice = _StubModel

# Stub relationship tables
user_application_assignments = None
group_application_assignments = None
user_group_memberships = None

# Stub enums (these might still be imported for type checking)
class PolicyType(enum.Enum):
    OKTA_SIGN_ON = "OKTA_SIGN_ON"
    PASSWORD = "PASSWORD"
    MFA_ENROLL = "MFA_ENROLL"
    IDP_DISCOVERY = "IDP_DISCOVERY"
    ACCESS_POLICY = "ACCESS_POLICY"
    PROFILE_ENROLLMENT = "PROFILE_ENROLLMENT"
    POST_AUTH_SESSION = "POST_AUTH_SESSION"
    ENTITY_RISK = "ENTITY_RISK"

class FactorType(enum.Enum):
    SMS = "sms"
    EMAIL = "email"
    CALL = "call"
    PUSH = "push"
    TOTP = "token:software:totp"
    HOTP = "token:software:hotp"
    HARDWARE = "token:hardware"
    SECURITY_QUESTION = "question"
    WEBAUTHN = "webauthn"
    FASTPASS = "signed_nonce"

class SyncStatus(enum.Enum):
    """Status of a sync operation"""
    IDLE = "idle"
    RUNNING = "running" 
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    SUCCESS = "completed"   

# Add these fields to your SyncHistory class
class SyncHistory(Base):
    __tablename__ = "sync_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, nullable=False, index=True)
    sync_type = Column(String, default='sqlite', nullable=False)  # 'sqlite' or 'graphdb'
    entity_type = Column(String, nullable=True)  # Add this field for SyncOrchestrator compatibility
    last_successful_sync = Column(DateTime(timezone=True), nullable=True)  # Add this field
    start_time = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    sync_end_time = Column(DateTime(timezone=True), nullable=True)  # Add alias for end_time
    status = Column(SQLEnum(SyncStatus), default=SyncStatus.IDLE, nullable=False)
    success = Column(Boolean, default=False)
    error_details = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)  # Add alias for error_details
    
    # Entity counts
    users_count = Column(Integer, default=0)
    groups_count = Column(Integer, default=0)
    apps_count = Column(Integer, default=0)
    policies_count = Column(Integer, default=0)
    devices_count = Column(Integer, default=0)
    records_processed = Column(Integer, default=0)  
    
    # Progress tracking
    progress_percentage = Column(Integer, default=0)
    
    # Process tracking (for cancellation)
    process_id = Column(String, nullable=True)
    
    # GraphDB specific fields
    graphdb_version = Column(Integer, nullable=True)  # Version number if syncing to GraphDB
    graphdb_promoted = Column(Boolean, default=False)  # Whether staging was promoted
    
    # Indexes for frequent queries
    __table_args__ = (
        Index('idx_sync_history_tenant_status', 'tenant_id', 'status'),
        Index('idx_sync_history_tenant_time', 'tenant_id', 'start_time'),
        Index('idx_sync_history_entity_type', 'entity_type'),  # Add index for entity_type
    )

    # Add this property to handle the SUCCESS vs COMPLETED mismatch
    @property
    def SUCCESS(self):
        return SyncStatus.COMPLETED 

# class Device(BaseModel):
#     __tablename__ = 'devices'
#     
#     # Basic device info from API response
#     status = Column(String, index=True)  # ACTIVE, etc.
#     
#     # Profile fields (all from API response)
#     display_name = Column(String, index=True)
#     platform = Column(String, index=True)  # ANDROID, iOS, WINDOWS, etc.
#     manufacturer = Column(String, index=True)
#     model = Column(String)
#     os_version = Column(String)
#     registered = Column(Boolean, default=False)
#     secure_hardware_present = Column(Boolean, default=False)
#     disk_encryption_type = Column(String)  # USER, NONE, etc.
#     
#     # Additional device attributes
#     serial_number = Column(String, index=True)  # Device serial number
#     udid = Column(String, index=True)  # Unique device identifier
#     
#     # Relationships
#     user_devices = relationship('UserDevice', back_populates='device', cascade='all, delete-orphan')
# 
#     __table_args__ = (
#         Index('idx_device_tenant_name', 'tenant_id', 'display_name'),
#         Index('idx_device_platform', 'tenant_id', 'platform'),
#         Index('idx_device_manufacturer', 'tenant_id', 'manufacturer'),
#         Index('idx_device_serial', 'tenant_id', 'serial_number'),
#         Index('idx_device_udid', 'tenant_id', 'udid'),
#         {'extend_existing': True}
#     )
# 
# class UserDevice(SyncBase):
#     __tablename__ = 'user_devices'
#     
#     user_okta_id = Column(String, ForeignKey('users.okta_id', ondelete='CASCADE'), index=True)
#     device_okta_id = Column(String, ForeignKey('devices.okta_id', ondelete='CASCADE'), index=True)
#     management_status = Column(String)  # NOT_MANAGED, MANAGED, etc.
#     user_device_created_at = Column(DateTime(timezone=True))  # Per-user creation date
#     screen_lock_type = Column(String)  # BIOMETRIC, PIN, PASSWORD, etc.
#     
#     # Relationships
#     user = relationship('User', foreign_keys=[user_okta_id])
#     device = relationship('Device', foreign_keys=[device_okta_id])
#     
#     __table_args__ = (
#         Index('idx_user_device_user', 'tenant_id', 'user_okta_id'),
#         Index('idx_user_device_device', 'tenant_id', 'device_okta_id'),
#         Index('idx_user_device_mgmt_status', 'tenant_id', 'management_status'),
#         Index('idx_user_device_screen_lock', 'tenant_id', 'screen_lock_type'),
#         UniqueConstraint('tenant_id', 'user_okta_id', 'device_okta_id', 
#                         name='uix_user_device_tenant_user_device'),
#         {'extend_existing': True}
#     )    
    
# Authentication Models
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"

class AuthUser(Base):
    """User model for authentication"""
    __tablename__ = "auth_users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.ADMIN, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    
    # Keep track of whether initial setup has been completed
    setup_completed = Column(Boolean, default=False, nullable=False)
    
    # For security, add login tracking
    last_login = Column(DateTime, nullable=True)
    login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<AuthUser username={self.username}, role={self.role}>"    