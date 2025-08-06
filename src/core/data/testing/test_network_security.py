#!/usr/bin/env python3
"""
Test Network Security Module

Quick test to verify URL validation is working as expected.
"""

import sys
import os
from pathlib import Path

# Add project paths
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "src"))

# Load environment variables (simulating main.py behavior)
from dotenv import load_dotenv
load_dotenv()

# Import from the correct path
sys.path.append(str(project_root / "src" / "core" / "security"))
from network_security import validate_url, validate_request

def test_network_security():
    """Test network security validation"""
    
    print("🔒 Testing Network Security Module")
    print("=" * 50)
    
    # Get the configured Okta tenant from environment
    okta_url = os.environ.get('OKTA_CLIENT_ORGURL', '')
    print(f"📋 Configured Okta Tenant: {okta_url}")
    print()
    
    # Test cases
    test_cases = [
        {
            "name": "Valid Okta API URL",
            "url": f"{okta_url}/api/v1/users",
            "expected": True
        },
        {
            "name": "Valid Okta OAuth URL", 
            "url": f"{okta_url}/oauth2/default/.well-known/oauth-authorization-server",
            "expected": True
        },
        {
            "name": "Invalid domain (Google)",
            "url": "https://google.com/api/v1/users",
            "expected": False
        },
        {
            "name": "Localhost (blocked)",
            "url": "https://localhost:8080/api/v1/users",
            "expected": False
        },
        {
            "name": "Non-HTTPS URL",
            "url": f"{okta_url}/api/v1/users".replace('https://', 'http://'),
            "expected": False
        },
        {
            "name": "Invalid API path",
            "url": f"{okta_url}/admin/users",
            "expected": False
        },
        {
            "name": "Malicious pattern (script)",
            "url": f"{okta_url}/api/v1/users?<script>alert('xss')</script>",
            "expected": False
        },
        {
            "name": "Path traversal attempt",
            "url": f"{okta_url}/api/v1/../../../etc/passwd",
            "expected": False
        }
    ]
    
    # Run URL validation tests
    print("🧪 URL Validation Tests:")
    print("-" * 30)
    
    passed = 0
    total = len(test_cases)
    
    for test in test_cases:
        result = validate_url(test["url"])
        success = result.is_allowed == test["expected"]
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} | {test['name']}")
        
        if not success:
            print(f"   Expected: {test['expected']}, Got: {result.is_allowed}")
            if result.violations:
                print(f"   Violations: {result.violations}")
            print(f"   Risk Level: {result.risk_level}")
        
        if success:
            passed += 1
        
        print()
    
    # Test HTTP request validation
    print("🌐 HTTP Request Validation Tests:")
    print("-" * 35)
    
    # Valid GET request
    valid_url = f"{okta_url}/api/v1/users"
    get_result = validate_request("GET", valid_url)
    get_status = "✅ PASS" if get_result.is_allowed else "❌ FAIL"
    print(f"{get_status} | Valid GET request")
    if get_result.is_allowed:
        passed += 1
    total += 1
    
    # Invalid POST request (not allowed)
    post_result = validate_request("POST", valid_url)
    post_status = "✅ PASS" if not post_result.is_allowed else "❌ FAIL"
    print(f"{post_status} | Invalid POST request (should be blocked)")
    if not post_result.is_allowed:
        passed += 1
    total += 1
    
    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Network security is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Please review the network security configuration.")
        return False

if __name__ == "__main__":
    test_network_security()
