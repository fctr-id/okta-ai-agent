from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer, Table, Index, UniqueConstraint, Text, JSON, Enum as SQLEnum
from sqlalchemy.sql import func, text
from datetime import datetime
import enum

Base = declarative_base()

class BaseModel(Base):
    __abstract__ = True
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    okta_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, index=True)
    is_deleted = Column(Boolean, default=False, index=True)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'okta_id', name='uix_tenant_okta_id'),
        Index('idx_tenant_deleted', 'tenant_id', 'is_deleted')
    )

class SyncBase(Base):
    __abstract__ = True
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)    

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

# Direct user-application assignments
user_application_assignments = Table(
    'user_application_assignments',
    Base.metadata,
    Column('user_okta_id', String, ForeignKey('users.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('application_okta_id', String, ForeignKey('applications.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('tenant_id', String, nullable=False),
    Column('assignment_id', String, nullable=False),  # appAssignmentId from appLinks
    Column('app_instance_id', String, nullable=False),  # appInstanceId from appLinks
    Column('credentials_setup', Boolean, default=False),
    Column('hidden', Boolean, default=False),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    Index('idx_user_app_tenant', 'tenant_id'),
    UniqueConstraint('tenant_id', 'user_okta_id', 'application_okta_id', name='uix_user_app_assignment')
)

# Group-application assignments
group_application_assignments = Table(
    'group_application_assignments',
    Base.metadata,
    Column('group_okta_id', String, ForeignKey('groups.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('application_okta_id', String, ForeignKey('applications.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('tenant_id', String, nullable=False),
    Column('assignment_id', String, nullable=False),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    Index('idx_group_app_tenant', 'tenant_id'),
    UniqueConstraint('tenant_id', 'group_okta_id', 'application_okta_id', name='uix_group_app_assignment')
)

# User-group memberships
user_group_memberships = Table(
    'user_group_memberships',
    Base.metadata,
    Column('user_okta_id', String, ForeignKey('users.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('group_okta_id', String, ForeignKey('groups.okta_id', ondelete='CASCADE'), primary_key=True),
    Column('tenant_id', String, nullable=False),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    Index('idx_user_group_tenant', 'tenant_id'),
    UniqueConstraint('tenant_id', 'user_okta_id', 'group_okta_id', name='uix_user_group_membership')
)

class User(BaseModel):
    __tablename__ = 'users'
    
    email = Column(String, index=True)
    first_name = Column(String)
    last_name = Column(String)
    login = Column(String, index=True)
    status = Column(String, index=True)
    
    #groups = relationship('Group', secondary=user_groups, back_populates='users', passive_deletes=True)
    #authenticators = relationship('Authenticator', secondary=user_authenticators, back_populates='users', passive_deletes=True)
    # Direct application assignments
    direct_applications = relationship('Application',secondary=user_application_assignments,back_populates='direct_users',passive_deletes=True)
    # Group memberships
    groups = relationship('Group',secondary=user_group_memberships,back_populates='users',passive_deletes=True)
    factors = relationship('UserFactor', back_populates='user', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('idx_user_tenant_email', 'tenant_id', 'email'),
        Index('idx_user_tenant_login', 'tenant_id', 'login'),
        {'extend_existing': True}
    )

class Group(BaseModel):
    __tablename__ = 'groups'
    
    name = Column(String, index=True)
    description = Column(String)
    
    # User memberships
    users = relationship('User',secondary=user_group_memberships,back_populates='groups',passive_deletes=True)
    
    # Application assignments
    applications = relationship('Application',secondary=group_application_assignments,back_populates='assigned_groups',passive_deletes=True)


    __table_args__ = (
        Index('idx_group_tenant_name', 'tenant_id', 'name'),
        {'extend_existing': True}
    )

class Authenticator(BaseModel):
    __tablename__ = 'authenticators'
    
    name = Column(String, index=True)
    status = Column(String, index=True)
    type = Column(String, index=True)
    
    #users = relationship('User', secondary=user_authenticators, back_populates='authenticators', passive_deletes=True)

    __table_args__ = (
        Index('idx_auth_tenant_name', 'tenant_id', 'name'),
        {'extend_existing': True}
    )

class Application(BaseModel):
    __tablename__ = 'applications'
    
    # Required fields
    okta_id = Column(String, nullable=False, index=True)
    name = Column(String, index=True)
    label = Column(String)
    status = Column(String, index=True)
    sign_on_mode = Column(String, index=True)
    
    # URLs and Integration
    metadata_url = Column(String, nullable=True)
    policy_id = Column(String, ForeignKey('policies.okta_id', ondelete='SET NULL'), nullable=True, index=True)
    sign_on_url = Column(String, nullable=True)
    audience = Column(String, nullable=True)
    destination = Column(String, nullable=True)
    
    # Authentication
    signing_kid = Column(String, nullable=True)
    username_template = Column(String, nullable=True)
    username_template_type = Column(String, nullable=True)
    
    # Settings
    implicit_assignment = Column(Boolean, default=False)
    admin_note = Column(Text, nullable=True)
    
    # SAML Settings
    attribute_statements = Column(JSON, nullable=True, default=[])
    honor_force_authn = Column(Boolean, default=False)
    
    # Visibility
    hide_ios = Column(Boolean, default=False)
    hide_web = Column(Boolean, default=False)
    
    # Timestamps and flags
    created_at = Column(DateTime, nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    
    # Relationships
    policy = relationship('Policy', foreign_keys=[policy_id], back_populates='applications')
    # Direct user assignments
    direct_users = relationship('User',secondary=user_application_assignments,back_populates='direct_applications',passive_deletes=True)
    
    # Group assignments
    assigned_groups = relationship('Group',secondary=group_application_assignments,back_populates='applications',passive_deletes=True)

    #__table_args__ = (
    #    Index('idx_app_tenant_name', 'tenant_id', 'name'),
    #    {'extend_existing': True}
    #)

    __table_args__ = (
        Index('idx_app_tenant_name', 'tenant_id', 'name'),
        Index('idx_app_okta_id', 'okta_id'),
        Index('idx_app_status', 'status'),
        Index('idx_app_sign_on_mode', 'sign_on_mode'),
        Index('idx_app_policy', 'policy_id'),
        Index('idx_app_attrs', 'attribute_statements', sqlite_where=text("json_valid(attribute_statements)")),
        {'extend_existing': True}
    )
     

class PolicyType(enum.Enum):
    OKTA_SIGN_ON = "OKTA_SIGN_ON"
    PASSWORD = "PASSWORD"
    MFA_ENROLL = "MFA_ENROLL"
    IDP_DISCOVERY = "IDP_DISCOVERY"
    ACCESS_POLICY = "ACCESS_POLICY"
    PROFILE_ENROLLMENT = "PROFILE_ENROLLMENT"
    POST_AUTH_SESSION = "POST_AUTH_SESSION"
    ENTITY_RISK = "ENTITY_RISK"
    
class Policy(BaseModel):
    __tablename__ = 'policies'
    
    okta_id = Column(String, nullable=False, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    status = Column(String, index=True)
    type = Column(String, index=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    
    # Relationships
    applications = relationship('Application', back_populates='policy', foreign_keys='Application.policy_id')

    __table_args__ = (
        Index('idx_policy_tenant_name', 'tenant_id', 'name'),
        Index('idx_policy_okta_id', 'okta_id'),
        Index('idx_policy_type', 'type'),
        {'extend_existing': True}
    )
    
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
    
class UserFactor(BaseModel):
    __tablename__ = 'user_factors'
    
    okta_id = Column(String, index=True, nullable=False)
    user_okta_id = Column(String, ForeignKey('users.okta_id', ondelete='CASCADE'))
    factor_type = Column(String, index=True)
    provider = Column(String, index=True)
    status = Column(String, index=True)
    
    # New timestamp fields
    created_at = Column(DateTime, nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    
    # Factor type specific fields
    email = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    
    user = relationship('User', 
                       foreign_keys=[user_okta_id],
                       primaryjoin="and_(UserFactor.user_okta_id==User.okta_id, "
                                 "UserFactor.tenant_id==User.tenant_id)")

    __table_args__ = (
        Index('idx_factor_tenant_user', 'tenant_id', 'user_okta_id'),
        Index('idx_factor_okta_id', 'okta_id'),
        Index('idx_factor_type_status', 'factor_type', 'status'),
        Index('idx_factor_provider_status', 'provider', 'status'),
        {'extend_existing': True}
    )
    
class SyncStatus(enum.Enum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class SyncHistory(SyncBase):
    __tablename__ = 'sync_history'
    
    entity_type = Column(String, nullable=False, index=True)
    sync_start_time = Column(DateTime, default=func.now())
    sync_end_time = Column(DateTime)
    status = Column(SQLEnum(SyncStatus), nullable=False, default=SyncStatus.STARTED)
    records_processed = Column(Integer, default=0)
    last_successful_sync = Column(DateTime)
    error_message = Column(String)

    __table_args__ = (
        Index('idx_sync_tenant_entity', 'tenant_id', 'entity_type'),
        {'extend_existing': True}
    )   