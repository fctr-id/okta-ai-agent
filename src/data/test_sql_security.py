"""
Test SQL Security Validator
"""
import asyncio
from sql_security_validator import validate_user_sql, validate_internal_sql, SQLSecurityValidator, SQLAgentType

def test_user_sql_validation():
    """Test user SQL validation - should only allow SELECT queries"""
    print("=== Testing User SQL Agent Validation ===")
    
    # Valid user queries
    valid_queries = [
        "SELECT * FROM users WHERE status = 'ACTIVE'",
        "SELECT u.*, g.name FROM users u JOIN user_group_memberships ugm ON u.okta_id = ugm.user_okta_id JOIN groups g ON ugm.group_okta_id = g.okta_id",
        "WITH active_users AS (SELECT * FROM users WHERE status = 'ACTIVE') SELECT * FROM active_users",
    ]
    
    for query in valid_queries:
        is_valid, error = validate_user_sql(query, "test-001")
        print(f"✅ Valid: {query[:50]}... -> {is_valid}")
        if not is_valid:
            print(f"   Error: {error}")
    
    # Invalid user queries
    invalid_queries = [
        "DELETE FROM users WHERE status = 'INACTIVE'",
        "INSERT INTO users (email) VALUES ('test@example.com')",
        "UPDATE users SET status = 'ACTIVE' WHERE okta_id = '123'",
        "CREATE TABLE temp_data (id TEXT)",
        "DROP TABLE users",
        "SELECT * FROM users; DROP TABLE users",
        "PRAGMA table_info(users)",
        "ATTACH DATABASE 'other.db' AS other",
    ]
    
    for query in invalid_queries:
        is_valid, error = validate_user_sql(query, "test-001")
        print(f"❌ Invalid: {query[:50]}... -> {is_valid}")
        if not is_valid:
            print(f"   Error: {error}")

def test_internal_sql_validation():
    """Test internal SQL validation - should allow temp tables"""
    print("\n=== Testing Internal SQL Agent Validation ===")
    
    # Valid internal queries
    valid_queries = [
        "SELECT * FROM users WHERE status = 'ACTIVE'",
        "CREATE TEMP TABLE temp_api_users (okta_id TEXT PRIMARY KEY, email TEXT)",
        "CREATE TEMPORARY TABLE temp_data_123 (id TEXT, name TEXT)",
        "SELECT u.* FROM users u JOIN temp_api_users tau ON u.okta_id = tau.okta_id",
        "DROP TABLE IF EXISTS temp_api_users",
    ]
    
    for query in valid_queries:
        is_valid, error = validate_internal_sql(query, "test-002")
        print(f"✅ Valid: {query[:50]}... -> {is_valid}")
        if not is_valid:
            print(f"   Error: {error}")
    
    # Invalid internal queries
    invalid_queries = [
        "DELETE FROM users WHERE status = 'INACTIVE'",
        "INSERT INTO users (email) VALUES ('test@example.com')",
        "CREATE TABLE users_backup AS SELECT * FROM users",  # No temp prefix
        "DROP TABLE users",  # Can't drop real tables
        "PRAGMA table_info(users)",
        "ATTACH DATABASE 'other.db' AS other",
        "CREATE TEMP TABLE bad_name (id TEXT)",  # No temp_ prefix
    ]
    
    for query in invalid_queries:
        is_valid, error = validate_internal_sql(query, "test-002")
        print(f"❌ Invalid: {query[:50]}... -> {is_valid}")
        if not is_valid:
            print(f"   Error: {error}")

def test_comprehensive_security():
    """Test comprehensive security features"""
    print("\n=== Testing Comprehensive Security Features ===")
    
    validator = SQLSecurityValidator()
    
    # Test SQL injection patterns
    injection_attempts = [
        "SELECT * FROM users WHERE email = 'user@example.com'; DROP TABLE users",
        "SELECT * FROM users WHERE id = '1' OR '1'='1'",
        "SELECT * FROM users WHERE name = 'test' UNION SELECT password FROM admin_users",
        "SELECT * FROM users /* comment */ WHERE status = 'ACTIVE'",
        "SELECT * FROM users WHERE email = 'test@example.com' --",
        "SELECT * FROM users WHERE id = 1; EXEC xp_cmdshell('dir')",
    ]
    
    for injection in injection_attempts:
        user_valid, user_error = validator.validate_sql(injection, SQLAgentType.USER, "test-003")
        internal_valid, internal_error = validator.validate_sql(injection, SQLAgentType.INTERNAL, "test-003")
        
        print(f"🛡️  Injection: {injection[:50]}...")
        print(f"   User Agent: {user_valid} ({user_error[:50] if user_error else 'OK'})")
        print(f"   Internal Agent: {internal_valid} ({internal_error[:50] if internal_error else 'OK'})")

def test_safe_query_examples():
    """Test the safe query examples provided by the validator"""
    print("\n=== Testing Safe Query Examples ===")
    
    validator = SQLSecurityValidator()
    
    # Test user examples
    user_examples = validator.get_safe_query_examples(SQLAgentType.USER)
    print("User Agent Safe Examples:")
    for example in user_examples:
        is_valid, error = validator.validate_sql(example, SQLAgentType.USER, "test-004")
        print(f"✅ {example[:50]}... -> {is_valid}")
    
    # Test internal examples
    internal_examples = validator.get_safe_query_examples(SQLAgentType.INTERNAL)
    print("\nInternal Agent Safe Examples:")
    for example in internal_examples:
        is_valid, error = validator.validate_sql(example, SQLAgentType.INTERNAL, "test-004")
        print(f"✅ {example[:50]}... -> {is_valid}")

if __name__ == "__main__":
    print("🔒 SQL Security Validator Test Suite")
    print("=" * 50)
    
    test_user_sql_validation()
    test_internal_sql_validation()
    test_comprehensive_security()
    test_safe_query_examples()
    
    print("\n🎯 Security validation testing completed!")
