# Okta AI Agent - Data Directory

This directory contains the essential files for the LLM-based Okta API endpoint filtering system.

## 📁 File Overview

### 🎯 **Core System Files**

#### `generic_endpoint_filter.py`
- **Main filtering system** with zero hardcoded logic
- Provides LLM1 entity discovery and LLM2 endpoint filtering
- Uses completely generic rule-based matching
- **Usage**: `from generic_endpoint_filter import GenericEndpointFilter`

#### `okta_endpoints_optimized.json` (292KB)
- **Primary data source** - 362 optimized endpoints from full Postman collection
- Rich metadata: entity_type, operation_type, keywords, use_cases, priorities
- Structured for efficient LLM1 discovery and LLM2 code generation
- **Generated from**: Full Postman collection via intelligent processing

#### `okta_schema.json`
- **SQL database schema** for LLM1 strategic decision making
- Used to determine when to prefer database queries over API calls
- Contains table definitions and relationships

#### `llm1_system_prompt.txt`
- **System prompt** for LLM1 strategic reasoning
- Guides LLM1 to choose optimal strategy (sql_only/api_only/hybrid)
- Instructs on entity identification and operation selection

### 🔄 **Utility Files**

#### `postman_to_llm_converter.py`
- **Converter tool** for processing raw Postman collections
- Transforms Postman JSON into LLM-optimized format
- Uses intelligent rules to extract entity types, operations, keywords
- **Usage**: Run when you need to update from new Postman exports

## 🚀 **Quick Start**

### Basic Usage
```python
from generic_endpoint_filter import GenericEndpointFilter

# Initialize the filter system
filter_system = GenericEndpointFilter("src/data")

# Create LLM1 input for entity discovery
llm1_input = filter_system.create_llm1_input("Find users with admin roles")

# After LLM1 decision, filter endpoints for LLM2
llm1_output = {"entities": ["user", "role"], "operations": ["list"], "methods": ["GET"]}
llm2_input = filter_system.filter_endpoints_for_llm2(llm1_output)

print(f"Sending {llm2_input['endpoint_count']} endpoints to LLM2")
```

### Update from New Postman Collection
```python
from postman_to_llm_converter import PostmanToLLMConverter

# Convert new Postman collection
converter = PostmanToLLMConverter("src/data")
output_file = converter.convert_postman_to_llm_format()
```

## 📊 **Architecture Benefits**

- **🎯 Minimal Context**: Reduces LLM2 input from 109+ to 6 endpoints (94% reduction)
- **🧠 Zero Hardcoding**: All matching rules driven by endpoint metadata
- **📦 Single Source**: One optimized file instead of multiple overlapping sources
- **🔄 Maintainable**: Easy to update from new Postman exports
- **📈 Scalable**: Add new entities without code changes

## 🧹 **Cleaned Up**

**Removed obsolete files:**
- `llm1_filter.py` - Old system with hardcoded logic
- `test_llm1_with_agent.py` - Test file for old system  
- `okta_api_methods_only.json` - Lightweight file (replaced)
- `Okta_Json_API_Refeerence_llm.json` - Manual reference (replaced)
- `full_postman_collection.json` - Raw 3.3MB collection (processed)

**Total space saved**: ~3.5MB of redundant files
**Files remaining**: 5 essential files (~320KB total)
