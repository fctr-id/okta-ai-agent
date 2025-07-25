"""
SQL Security Validator - Comprehensive SQL injection protection and operation validation
"""
import re
import logging
from typing import List, Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class SQLAgentType(Enum):
    """Types of SQL agents with different privilege levels"""
    USER = "user"          # User-facing agent with strict restrictions
    INTERNAL = "internal"   # Internal agent with temp table privileges

class SecurityLevel(Enum):
    """Security validation levels"""
    STRICT = "strict"      # User-facing operations (SELECT only)
    ELEVATED = "elevated"  # Internal operations (SELECT + temp tables)

class SQLSecurityValidator:
    """Comprehensive SQL security validation"""
    
    def __init__(self):
        # Base dangerous patterns - blocked for ALL agents
        self.base_dangerous_patterns = [
            # Data modification
            r'\bdelete\s+from\b',
            r'\binsert\s+into\b',
            r'\bupdate\s+.*\s+set\b',
            r'\btruncate\s+table\b',
            
            # Schema modification
            r'\bdrop\s+(table|database|schema|view|index)\b',
            r'\balter\s+table\b',
            r'\bcreate\s+(database|schema|index|view)\b',
            
            # System operations
            r'\bexec\s*\(',
            r'\bexecute\s*\(',
            r'\bcall\s+',
            r'\bprocedure\s+',
            
            # Multi-statement attacks
            r';\s*(drop|delete|insert|update|create|alter|truncate)',
            
            # Function injection
            r'\bxp_\w+',
            r'\bsp_\w+',
            
            # Union-based injection patterns (but allow legitimate UNIONs for user agents)
            # Block suspicious UNION patterns that don't match our prescribed patterns
            r'union\s+select\s+null\s*,\s*null\s*,\s*null\s*,\s*null\s*,\s*null',  # 5+ NULL columns (injection pattern)
            r'union\s+all\s+select\s+\d+\s*,',  # UNION with number literals (injection pattern)
            
            # Comment-based attacks
            r'/\*.*\*/',
            r'--.*drop',
            r'--.*delete',
            
            # SQLite specific dangerous functions
            r'\bload_extension\s*\(',
            r'\battach\s+database\b',
            r'\bdetach\s+database\b',
        ]
        
        # User agent additional restrictions
        self.user_restrictions = [
            # No table creation even temporary
            r'\bcreate\s+table\b',
            r'\bcreate\s+temp\s+table\b',
            r'\bcreate\s+temporary\s+table\b',
            
            # No pragma statements
            r'\bpragma\s+',
            
            # No database manipulation
            r'\bvacuum\b',
            r'\breindex\b',
        ]
        
        # Internal agent exceptions (allowed patterns)
        self.internal_allowed_patterns = [
            r'\bcreate\s+temp\s+table\s+temp_\w+',  # Only temp tables with temp_ prefix
            r'\bcreate\s+temporary\s+table\s+temp_\w+',
            r'\bdrop\s+table\s+if\s+exists\s+temp_\w+',  # Only drop temp tables
        ]
        
        # Required patterns for valid queries
        self.required_patterns = [
            r'\bselect\b',  # Must contain SELECT
        ]
        
        # Valid starting patterns
        self.valid_start_patterns = [
            r'^\s*select\b',
            r'^\s*with\b',  # CTEs are allowed
        ]

    def validate_sql(self, sql_query: str, agent_type: SQLAgentType, correlation_id: str = "") -> Tuple[bool, Optional[str]]:
        """
        Comprehensive SQL validation with agent-specific rules
        
        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        if not sql_query or not isinstance(sql_query, str):
            return False, "Empty or invalid SQL query"
        
        # Normalize and clean SQL
        cleaned_sql = self._clean_sql(sql_query)
        
        if not cleaned_sql:
            return False, "SQL query is empty after cleaning"
        
        # 1. Check query structure (with agent type awareness)
        structure_valid, structure_error = self._validate_structure(cleaned_sql, agent_type)
        if not structure_valid:
            return False, f"Structure validation failed: {structure_error}"
        
        # 2. Check for base dangerous patterns (applies to all agents)
        dangerous_valid, dangerous_error = self._check_dangerous_patterns(cleaned_sql)
        if not dangerous_valid:
            return False, f"Dangerous pattern detected: {dangerous_error}"
        
        # 3. Agent-specific validation
        if agent_type == SQLAgentType.USER:
            user_valid, user_error = self._validate_user_agent(cleaned_sql)
            if not user_valid:
                return False, f"User agent restriction: {user_error}"
        elif agent_type == SQLAgentType.INTERNAL:
            internal_valid, internal_error = self._validate_internal_agent(cleaned_sql)
            if not internal_valid:
                return False, f"Internal agent restriction: {internal_error}"
        
        # 4. Additional SQLite-specific checks
        sqlite_valid, sqlite_error = self._validate_sqlite_specific(cleaned_sql)
        if not sqlite_valid:
            return False, f"SQLite security check failed: {sqlite_error}"
        
        logger.debug(f"[{correlation_id}] SQL validation passed for {agent_type.value} agent")
        return True, None

    def _clean_sql(self, sql_query: str) -> str:
        """Clean and normalize SQL query"""
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', sql_query.strip())
        
        # Remove comments (but preserve the query structure)
        cleaned = re.sub(r'--.*$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
        
        # Normalize to lowercase for pattern matching
        return cleaned.lower()

    def _validate_structure(self, sql: str, agent_type: SQLAgentType) -> Tuple[bool, Optional[str]]:
        """Validate basic SQL structure with agent-specific rules"""
        
        # For internal agents, allow CREATE TEMPORARY TABLE statements
        if agent_type == SQLAgentType.INTERNAL:
            # Check if this is a temp table creation
            temp_table_patterns = [
                r'^\s*create\s+temp\s+table\s+temp_\w+',
                r'^\s*create\s+temporary\s+table\s+temp_\w+'
            ]
            if any(re.match(pattern, sql, re.IGNORECASE) for pattern in temp_table_patterns):
                # For temp table creation, just check balanced parentheses
                paren_count = sql.count('(') - sql.count(')')
                if paren_count != 0:
                    return False, "Unbalanced parentheses in query"
                return True, None
        
        # Standard validation for SELECT/WITH queries
        # Must start with SELECT or WITH
        if not any(re.match(pattern, sql) for pattern in self.valid_start_patterns):
            return False, "Query must start with SELECT or WITH"
        
        # Must contain SELECT somewhere
        if not any(re.search(pattern, sql) for pattern in self.required_patterns):
            return False, "Query must contain SELECT statement"
        
        # Check for balanced parentheses
        paren_count = sql.count('(') - sql.count(')')
        if paren_count != 0:
            return False, "Unbalanced parentheses in query"
        
        return True, None

    def _check_dangerous_patterns(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Check for dangerous SQL patterns"""
        for pattern in self.base_dangerous_patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return False, f"Dangerous operation detected: {match.group()}"
        
        return True, None

    def _validate_user_agent(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Validate SQL for user-facing agent with strict restrictions"""
        # Check user-specific restrictions
        for pattern in self.user_restrictions:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return False, f"User agent cannot perform: {match.group()}"
        
        # User agent must be pure SELECT queries
        if not re.match(r'^\s*(select|with)', sql):
            return False, "User agent can only execute SELECT or WITH queries"
        
        return True, None

    def _validate_internal_agent(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Validate SQL for internal agent with elevated privileges"""
        # Check if this uses any temp table operations
        temp_table_ops = [
            r'\bcreate\s+(temp|temporary)\s+table\b',
            r'\bdrop\s+table\s+if\s+exists\s+temp_\w+\b'
        ]
        
        has_temp_ops = any(re.search(pattern, sql) for pattern in temp_table_ops)
        
        if has_temp_ops:
            # Validate temp table operations are safe
            for pattern in self.internal_allowed_patterns:
                if re.search(pattern, sql):
                    continue  # This pattern is allowed
                else:
                    # Check if there are temp operations not in allowed patterns
                    for temp_op in temp_table_ops:
                        if re.search(temp_op, sql):
                            # Make sure it follows our naming convention
                            if not re.search(r'temp_\w+', sql):
                                return False, "Temp tables must use 'temp_' prefix"
        
        return True, None

    def _validate_sqlite_specific(self, sql: str) -> Tuple[bool, Optional[str]]:
        """SQLite-specific security checks"""
        # Block potentially dangerous SQLite functions
        dangerous_sqlite = [
            r'\bpragma\s+',
            r'\bload_extension\s*\(',
            r'\battach\s+database\b',
            r'\bdetach\s+database\b',
            r'\bvacuum\b',
            r'\breindex\b',
        ]
        
        for pattern in dangerous_sqlite:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return False, f"SQLite operation not allowed: {match.group()}"
        
        return True, None

    def get_safe_query_examples(self, agent_type: SQLAgentType) -> List[str]:
        """Get examples of safe queries for each agent type"""
        if agent_type == SQLAgentType.USER:
            return [
                "SELECT * FROM users WHERE status = 'ACTIVE'",
                "SELECT u.*, g.name as group_name FROM users u JOIN user_groups ug ON u.okta_id = ug.user_id JOIN groups g ON ug.group_id = g.okta_id",
                "WITH active_users AS (SELECT * FROM users WHERE status = 'ACTIVE') SELECT * FROM active_users WHERE email LIKE '%@company.com'"
            ]
        elif agent_type == SQLAgentType.INTERNAL:
            return [
                "SELECT * FROM users WHERE status = 'ACTIVE'",
                "CREATE TEMP TABLE temp_api_users (okta_id TEXT, email TEXT, status TEXT)",
                "SELECT u.* FROM users u WHERE u.okta_id IN (SELECT okta_id FROM temp_api_users)",
                "DROP TABLE IF EXISTS temp_api_users"
            ]
        return []

# Global validator instance
sql_validator = SQLSecurityValidator()

def validate_user_sql(sql_query: str, correlation_id: str = "") -> Tuple[bool, Optional[str]]:
    """Validate SQL for user-facing agent"""
    return sql_validator.validate_sql(sql_query, SQLAgentType.USER, correlation_id)

def validate_internal_sql(sql_query: str, correlation_id: str = "") -> Tuple[bool, Optional[str]]:
    """Validate SQL for internal agent"""
    return sql_validator.validate_sql(sql_query, SQLAgentType.INTERNAL, correlation_id)
