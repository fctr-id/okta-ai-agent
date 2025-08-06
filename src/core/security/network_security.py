"""
Network Security Module

Provides network-level security controls for the modern execution manager.
Implements simple but effective network restrictions:
- Blocks all HTTP traffic except to authorized Okta tenant
- URL validation and filtering
- Environment-based security configuration
"""

import os
import re
import logging
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class NetworkSecurityResult:
    """Result of network security validation"""
    is_allowed: bool
    violations: List[str]
    blocked_reason: Optional[str]
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'

class NetworkSecurityValidator:
    """Validates network requests against security policies"""
    
    def __init__(self):
        """Initialize network security validator"""
        # Get authorized Okta tenant from environment
        self.okta_tenant_url = os.environ.get('OKTA_CLIENT_ORGURL', '').rstrip('/')
        
        if not self.okta_tenant_url:
            logger.warning("OKTA_CLIENT_ORGURL not found in environment. Network security may not function properly.")
            self.okta_tenant_url = ''
        else:
            logger.info(f"Network security initialized for tenant: {self.okta_tenant_url}")
        
        # Parse the authorized domain
        if self.okta_tenant_url:
            parsed = urlparse(self.okta_tenant_url)
            self.authorized_domain = parsed.netloc.lower()
            self.authorized_scheme = parsed.scheme.lower()
        else:
            self.authorized_domain = ''
            self.authorized_scheme = 'https'
        
        # Blocked domains/patterns (known malicious or non-business)
        self.blocked_domains = {
            'localhost', '127.0.0.1', '0.0.0.0', '::1',
            'example.com', 'test.com', 'invalid',
            'bit.ly', 'tinyurl.com', 'short.link'  # URL shorteners
        }
        
        # Allowed Okta API paths only
        self.allowed_api_paths = [
            '/api/v1/',
            '/oauth2/',
            '/.well-known/',
            '/login/'
        ]
    
    def validate_url(self, url: str) -> NetworkSecurityResult:
        """
        Validate URL against network security policies
        
        Args:
            url: URL to validate
            
        Returns:
            NetworkSecurityResult with validation details
        """
        violations = []
        blocked_reason = None
        risk_level = 'LOW'
        
        # Basic URL validation
        if not url:
            violations.append("Empty URL provided")
            blocked_reason = "Invalid URL"
            risk_level = 'MEDIUM'
            return NetworkSecurityResult(False, violations, blocked_reason, risk_level)
        
        try:
            parsed = urlparse(url)
        except Exception as e:
            violations.append(f"Invalid URL format: {e}")
            blocked_reason = "URL parsing failed"
            risk_level = 'MEDIUM'
            return NetworkSecurityResult(False, violations, blocked_reason, risk_level)
        
        # Check scheme
        if parsed.scheme.lower() not in ['https', 'http']:
            violations.append(f"Unsupported URL scheme: {parsed.scheme}")
            blocked_reason = "Invalid scheme"
            risk_level = 'HIGH'
        
        # Enforce HTTPS for production
        if parsed.scheme.lower() != 'https':
            violations.append("Only HTTPS URLs are allowed")
            blocked_reason = "Non-HTTPS URL"
            risk_level = 'HIGH'
        
        # Check domain
        domain = parsed.netloc.lower()
        
        # Block localhost and invalid domains
        if domain in self.blocked_domains:
            violations.append(f"Blocked domain: {domain}")
            blocked_reason = "Domain on blocklist"
            risk_level = 'HIGH'
        
        # Check if domain matches authorized Okta tenant
        if self.authorized_domain and domain != self.authorized_domain:
            violations.append(f"Unauthorized domain: {domain}. Only {self.authorized_domain} is allowed.")
            blocked_reason = "Unauthorized domain"
            risk_level = 'CRITICAL'
        
        # Check API path
        path = parsed.path
        is_valid_api_path = any(path.startswith(allowed_path) for allowed_path in self.allowed_api_paths)
        
        if not is_valid_api_path:
            violations.append(f"Unauthorized API path: {path}")
            blocked_reason = "Invalid API path"
            risk_level = 'HIGH'
        
        # Check for suspicious patterns in URL
        suspicious_patterns = [
            r'\.\./', r'%2e%2e%2f', r'javascript:', r'data:', r'file:',
            r'<script', r'javascript', r'vbscript', r'onload', r'onerror'
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                violations.append(f"Suspicious pattern in URL: {pattern}")
                blocked_reason = "Malicious pattern detected"
                risk_level = 'CRITICAL'
                break
        
        is_allowed = len(violations) == 0
        
        return NetworkSecurityResult(
            is_allowed=is_allowed,
            violations=violations,
            blocked_reason=blocked_reason,
            risk_level=risk_level
        )
    
    def validate_request_data(self, method: str, url: str, headers: Optional[Dict] = None, 
                            data: Optional[Dict] = None) -> NetworkSecurityResult:
        """
        Validate complete HTTP request data
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            headers: Request headers (optional)
            data: Request data (optional)
            
        Returns:
            NetworkSecurityResult with validation details
        """
        violations = []
        blocked_reason = None
        risk_level = 'LOW'
        
        # Validate URL first
        url_result = self.validate_url(url)
        if not url_result.is_allowed:
            return url_result
        
        # Validate method (GET only for now)
        if method.upper() != 'GET':
            violations.append(f"HTTP method '{method}' not allowed. Only GET requests are permitted.")
            blocked_reason = "Non-GET method"
            risk_level = 'CRITICAL'
        
        # Check for data in GET requests
        if method.upper() == 'GET' and data:
            violations.append("GET requests should not contain request body data")
            blocked_reason = "Data in GET request"
            risk_level = 'MEDIUM'
        
        # Validate headers if provided
        if headers:
            for header_name, header_value in headers.items():
                # Check for suspicious headers
                if header_name.lower() in ['x-forwarded-for', 'x-real-ip', 'x-originating-ip']:
                    violations.append(f"Suspicious header: {header_name}")
                    blocked_reason = "Suspicious headers"
                    risk_level = 'HIGH'
                
                # Check for injection patterns in header values
                if isinstance(header_value, str):
                    injection_patterns = [r'<script', r'javascript:', r'data:', r'\.\./', r'\x00']
                    for pattern in injection_patterns:
                        if re.search(pattern, header_value, re.IGNORECASE):
                            violations.append(f"Injection pattern in header {header_name}: {pattern}")
                            blocked_reason = "Header injection"
                            risk_level = 'CRITICAL'
                            break
        
        is_allowed = len(violations) == 0
        
        return NetworkSecurityResult(
            is_allowed=is_allowed,
            violations=violations,
            blocked_reason=blocked_reason,
            risk_level=risk_level
        )
    
    def get_security_headers(self) -> Dict[str, str]:
        """
        Get recommended security headers for outbound requests
        
        Returns:
            Dictionary of security headers
        """
        return {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache'
        }

# Create a global network security validator instance (lazy initialization)
_network_validator = None

def _get_network_validator() -> NetworkSecurityValidator:
    """Get or create the global network security validator instance"""
    global _network_validator
    if _network_validator is None:
        _network_validator = NetworkSecurityValidator()
    return _network_validator

def validate_url(url: str) -> NetworkSecurityResult:
    """
    Convenience function to validate URL
    
    Args:
        url: URL to validate
        
    Returns:
        NetworkSecurityResult with validation details
    """
    return _get_network_validator().validate_url(url)

def validate_request(method: str, url: str, headers: Optional[Dict] = None, 
                    data: Optional[Dict] = None) -> NetworkSecurityResult:
    """
    Convenience function to validate HTTP request
    
    Args:
        method: HTTP method
        url: Request URL
        headers: Request headers (optional)
        data: Request data (optional)
        
    Returns:
        NetworkSecurityResult with validation details
    """
    return _get_network_validator().validate_request_data(method, url, headers, data)

def get_security_headers() -> Dict[str, str]:
    """
    Convenience function to get security headers
    
    Returns:
        Dictionary of security headers
    """
    return _get_network_validator().get_security_headers()
