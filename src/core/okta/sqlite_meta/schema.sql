-- SQLite Metadata Database Schema
-- Purpose: Operational metadata for authentication and sync status tracking
-- Database: okta_meta.db (separate from business data)
-- Created: October 6, 2025
-- Location: ../../sqlite_db/okta_meta.db (database file)
-- This file: src/core/okta/sqlite_meta/schema.sql (schema definition)

-- ============================================================================
-- Authentication Tables
-- ============================================================================

-- Local users for authentication
CREATE TABLE IF NOT EXISTS local_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster username lookups
CREATE INDEX IF NOT EXISTS idx_local_users_username ON local_users(username);
CREATE INDEX IF NOT EXISTS idx_local_users_email ON local_users(email);

-- ============================================================================
-- Sync Status Tracking Tables
-- ============================================================================

-- Sync history for status tracking (both SQLite and GraphDB syncs)
CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    sync_type TEXT DEFAULT 'sqlite',  -- 'sqlite' or 'graphdb'
    status TEXT NOT NULL,              -- 'running', 'completed', 'failed', 'canceled'
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    success BOOLEAN DEFAULT 0,
    error_details TEXT,
    
    -- Entity counts
    users_count INTEGER DEFAULT 0,
    groups_count INTEGER DEFAULT 0,
    apps_count INTEGER DEFAULT 0,
    policies_count INTEGER DEFAULT 0,
    devices_count INTEGER DEFAULT 0,
    records_processed INTEGER DEFAULT 0,
    
    -- Progress tracking
    progress_percentage INTEGER DEFAULT 0,
    
    -- Process tracking (for cancellation)
    process_id TEXT,
    
    -- GraphDB specific fields
    graphdb_version INTEGER,           -- Version number if syncing to GraphDB
    graphdb_promoted BOOLEAN DEFAULT 0 -- Whether staging was promoted
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_sync_history_tenant_status ON sync_history(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_sync_history_tenant_time ON sync_history(tenant_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_sync_history_sync_type ON sync_history(sync_type);

-- ============================================================================
-- Session Management (Optional)
-- ============================================================================

-- User sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    data TEXT,  -- JSON blob for additional session data
    FOREIGN KEY (user_id) REFERENCES local_users(id) ON DELETE CASCADE
);

-- Index for session lookups and expiration cleanup
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

-- ============================================================================
-- Triggers for automatic timestamp updates
-- ============================================================================

-- Update local_users.updated_at on modification
CREATE TRIGGER IF NOT EXISTS update_local_users_timestamp 
AFTER UPDATE ON local_users
BEGIN
    UPDATE local_users SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- ============================================================================
-- Initial Data / Migrations
-- ============================================================================

-- Note: Initial admin user should be created via script, not hardcoded here
-- Example: INSERT INTO local_users (username, email, password_hash) VALUES (?, ?, ?);

-- ============================================================================
-- Database Metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Record initial schema version
INSERT OR IGNORE INTO schema_version (version, description) 
VALUES (1, 'Initial metadata-only schema for auth and sync tracking');

-- ============================================================================
-- Views for Common Queries
-- ============================================================================

-- Active syncs view
CREATE VIEW IF NOT EXISTS active_syncs AS
SELECT * FROM sync_history
WHERE status IN ('running', 'idle')
ORDER BY start_time DESC;

-- Recent sync history view
CREATE VIEW IF NOT EXISTS recent_sync_history AS
SELECT * FROM sync_history
ORDER BY start_time DESC
LIMIT 50;

-- Failed syncs view (for troubleshooting)
CREATE VIEW IF NOT EXISTS failed_syncs AS
SELECT * FROM sync_history
WHERE status = 'failed'
ORDER BY start_time DESC;
