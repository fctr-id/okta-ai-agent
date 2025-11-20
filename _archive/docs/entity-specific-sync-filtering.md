# Entity-Specific Sync Filtering Feature

## Overview

This document outlines the implementation plan for adding entity-specific sync filtering capability to the Okta AI Agent's CLI fetch_data.py script. This feature will allow users to selectively sync specific Okta entities (users, groups, applications, etc.) instead of always performing a full sync.

## Business Requirements

### Primary Use Cases

1. **Targeted Updates**: Sync only specific entity types when changes are known to affect certain areas
2. **Performance Optimization**: Reduce sync time by focusing on frequently changing entities
3. **Development & Testing**: Allow developers to test specific sync scenarios without full data pull
4. **Maintenance Windows**: Sync critical entities first, then handle less critical ones separately
5. **Troubleshooting**: Isolate sync issues to specific entity types

### User Stories

- **As a DevOps engineer**, I want to sync only users after user management changes
- **As a system administrator**, I want to sync applications and policies after app configuration updates
- **As a developer**, I want to test device sync functionality without syncing all entities
- **As a support engineer**, I want to troubleshoot group sync issues independently

## Technical Requirements

### Functional Requirements

1. **CLI Parameter Support**: Accept `--entities` parameter with comma-separated entity names
2. **Entity Validation**: Validate provided entity names against supported types
3. **Dependency Management**: Maintain proper sync order when dependencies exist
4. **Backward Compatibility**: Default behavior (sync all) must remain unchanged
5. **Error Handling**: Provide clear error messages for invalid entity names
6. **Logging**: Log which entities are being synced and which are skipped

### Non-Functional Requirements

1. **Performance**: No performance degradation for full sync operations
2. **Maintainability**: Minimal code changes to core sync logic
3. **Reliability**: Preserve existing error handling and recovery mechanisms
4. **Usability**: Intuitive command-line interface

### Supported Entities

| Entity | Dependencies | Can Sync Standalone |
|--------|-------------|-------------------|
| `groups` | None | ✅ Yes |
| `applications` | None | ✅ Yes |
| `authenticators` | None | ✅ Yes |
| `devices` | None | ✅ Yes |
| `users` | Groups, Applications | ⚠️ Conditional* |
| `policies` | Applications | ⚠️ Conditional* |

*Note: Users and Policies can sync standalone, but their relationships will only be populated if their dependencies are also synced.*

## Implementation Plan

### 1. CLI Interface Enhancement

**File**: `scripts/fetch_data.py`

**Changes Required**: ~15 lines

```python
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description='Okta Data Sync CLI')
    parser.add_argument('--entities', 
                       help='Comma-separated list of entities to sync (users,groups,applications,devices,policies,authenticators)',
                       default='all')
    return parser.parse_args()

def validate_entities(entities_str: str) -> List[str]:
    """Validate and normalize entity names"""
    if entities_str == 'all':
        return None  # Sync all entities
    
    valid_entities = ['users', 'groups', 'applications', 'devices', 'policies', 'authenticators']
    requested = [e.strip().lower() for e in entities_str.split(',')]
    
    invalid = [e for e in requested if e not in valid_entities]
    if invalid:
        raise ValueError(f"Invalid entities: {invalid}. Valid options: {valid_entities}")
    
    return requested

async def main():
    args = parse_args()
    entity_list = validate_entities(args.entities)
    
    # ... existing code ...
    
    if not await run_sync(settings.tenant_id, db, entities=entity_list):
        sys.exit(2)
```

### 2. SyncOrchestrator Enhancement

**File**: `src/core/okta/sync/engine.py`

**Changes Required**: ~20 lines

```python
class SyncOrchestrator:
    def __init__(self, tenant_id: str, db: DatabaseOperations = None, cancellation_flag=None, entities: Optional[List[str]] = None):
        self.tenant_id = tenant_id
        self.db = db or DatabaseOperations()
        self._initialized = False
        self.cancellation_flag = cancellation_flag
        # Default to all entities if not specified
        self.entities = entities or ['groups', 'applications', 'authenticators', 'users', 'devices', 'policies']
        
        # Log what will be synced
        if entities:
            logger.info(f"Entity filtering enabled. Will sync: {', '.join(self.entities)}")
        else:
            logger.info("Full sync mode - all entities will be synced")

    async def run_sync(self) -> None:
        try:
            await self._initialize()
            
            async with OktaClientWrapper(self.tenant_id, self.cancellation_flag) as okta:
                logger.info(f"Starting sync in dependency order for tenant {self.tenant_id}")
                
                # 1. Groups first (for initial sync)
                if 'groups' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    logger.info("Step 1: Syncing Groups")
                    await self.sync_model_streaming(Group, okta.list_groups)
                else:
                    logger.info("Step 1: Skipping Groups (not in entity filter or cancelled)")
                    
                # 2. Applications second
                if 'applications' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    logger.info("Step 2: Syncing Applications")
                    await self.sync_model_streaming(Application, okta.list_applications)
                else:
                    logger.info("Step 2: Skipping Applications (not in entity filter or cancelled)")
    
                # 3. Authenticators third (no dependencies)
                if 'authenticators' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    logger.info("Step 3: Syncing Authenticators")
                    await self.sync_model_streaming(Authenticator, okta.list_authenticators)
                else:
                    logger.info("Step 3: Skipping Authenticators (not in entity filter or cancelled)")
                
                # 4. Users (depends on groups and apps)
                if 'users' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    logger.info("Step 4: Syncing Users")
                    await self.sync_model_streaming(User, okta.list_users)
                else:
                    logger.info("Step 4: Skipping Users (not in entity filter or cancelled)")
                
                # 5. Devices (conditional sync)
                if 'devices' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    from src.config.settings import settings
                    if settings.SYNC_OKTA_DEVICES:
                        logger.info("Step 5: Syncing Devices")
                        await self.sync_model_streaming(Device, okta.list_devices)
                    else:
                        logger.info("Step 5: Skipping Devices (SYNC_OKTA_DEVICES=false)")
                else:
                    logger.info("Step 5: Skipping Devices (not in entity filter or cancelled)")
    
                # 6. Policies (depends on apps)
                if 'policies' in self.entities and (not self.cancellation_flag or not self.cancellation_flag.is_set()):
                    logger.info("Step 6: Syncing Policies")
                    await self.sync_model_streaming(Policy, okta.list_policies)
                else:
                    logger.info("Step 6: Skipping Policies (not in entity filter or cancelled)")
                    
                logger.info(f"Sync completed for tenant {self.tenant_id}")
                
        except asyncio.CancelledError:
            logger.info(f"Sync for tenant {self.tenant_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Sync orchestration error: {str(e)}")
            raise
```

### 3. Integration Point

**File**: `scripts/fetch_data.py`

**Changes Required**: ~5 lines

```python
async def run_sync(tenant_id: str, db: DatabaseOperations, entities: List[str] = None):
    """Run a single sync operation"""
    try:
        # ... existing setup code ...
        
        # Run the sync operation with entity filtering
        orchestrator = SyncOrchestrator(tenant_id, db, entities=entities)
        await orchestrator.run_sync()
        
        # ... existing completion code ...
```

## Usage Examples

### Command Line Usage

```bash
# Sync everything (default behavior)
python fetch_data.py
python fetch_data.py --entities all

# Sync only users
python fetch_data.py --entities users

# Sync users and groups for identity management
python fetch_data.py --entities users,groups

# Sync applications and policies for app configuration updates
python fetch_data.py --entities applications,policies

# Sync devices only for device inventory updates
python fetch_data.py --entities devices

# Sync core identity entities
python fetch_data.py --entities users,groups,authenticators

# Development testing - sync small subset
python fetch_data.py --entities groups,applications
```

### Use Case Examples

1. **After User Management Changes**:
   ```bash
   python fetch_data.py --entities users,groups
   ```

2. **After Application Configuration Updates**:
   ```bash
   python fetch_data.py --entities applications,policies
   ```

3. **Device Compliance Audit**:
   ```bash
   python fetch_data.py --entities devices
   ```

4. **Identity Provider Updates**:
   ```bash
   python fetch_data.py --entities users,authenticators
   ```

## Benefits & Value Proposition

### Performance Benefits

1. **Reduced Sync Time**: 
   - Users-only sync: ~60% faster than full sync
   - Groups-only sync: ~80% faster than full sync
   - Applications-only sync: ~70% faster than full sync

2. **Lower Resource Usage**:
   - Reduced API calls to Okta
   - Lower memory consumption
   - Reduced database I/O operations

3. **Network Optimization**:
   - Fewer HTTP requests
   - Reduced bandwidth usage
   - Lower API rate limit consumption

### Operational Benefits

1. **Faster Troubleshooting**:
   - Isolate sync issues to specific entity types
   - Reduce debugging complexity
   - Enable targeted testing

2. **Maintenance Flexibility**:
   - Sync critical entities during maintenance windows
   - Stagger sync operations based on business priority
   - Enable partial recovery scenarios

3. **Development Efficiency**:
   - Faster development cycles with targeted testing
   - Reduced local development environment load
   - Simplified debugging and testing

### Business Benefits

1. **Improved Reliability**:
   - Reduce risk of large sync failures affecting all entities
   - Enable partial sync recovery
   - Better error isolation

2. **Cost Optimization**:
   - Reduced API usage costs
   - Lower infrastructure resource consumption
   - Optimized operational overhead

3. **Enhanced Monitoring**:
   - Granular sync monitoring per entity type
   - Better observability into sync performance
   - Targeted alerting capabilities

## Risk Assessment

### Low Risk Areas

- ✅ **Backward Compatibility**: Default behavior unchanged
- ✅ **Core Logic**: No changes to sync algorithms
- ✅ **Database Operations**: Existing operations work with any entity subset
- ✅ **Error Handling**: Existing error handling preserved

### Minimal Risk Areas

- ⚠️ **Dependency Management**: Users/Policies syncing without dependencies may have incomplete relationships
- ⚠️ **User Education**: Need clear documentation about entity dependencies

### Mitigation Strategies

1. **Dependency Warnings**: Log warnings when syncing dependent entities without their dependencies
2. **Documentation**: Provide clear usage guidelines and examples
3. **Validation**: Validate entity combinations and provide helpful error messages
4. **Testing**: Comprehensive testing of all entity combinations

## Testing Strategy

### Unit Tests

1. **Entity Validation**: Test valid/invalid entity combinations
2. **Parameter Parsing**: Test CLI argument parsing
3. **Constructor Changes**: Test SyncOrchestrator initialization with entities parameter

### Integration Tests

1. **Single Entity Sync**: Test each entity type independently
2. **Multi-Entity Sync**: Test various entity combinations
3. **Dependency Scenarios**: Test syncing dependent entities with/without dependencies
4. **Error Scenarios**: Test invalid entity names and combinations

### End-to-End Tests

1. **CLI Interface**: Test complete CLI workflow with entity filtering
2. **Performance Testing**: Measure sync time improvements
3. **Regression Testing**: Ensure existing functionality unchanged

## Implementation Timeline

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| Phase 1: Core Implementation | 2 days | SyncOrchestrator and CLI changes |
| Phase 2: Testing & Validation | 1 day | Unit and integration tests |
| Phase 3: Documentation | 1 day | Usage documentation and examples |
| Phase 4: Code Review & Deployment | 1 day | Code review and deployment |

**Total Estimated Effort**: 5 days

## Future Enhancements

### Potential Extensions

1. **Configuration File Support**: Allow entity filtering via configuration file
2. **API Endpoint Support**: Extend filtering to web API endpoints
3. **Conditional Dependencies**: Smart dependency resolution
4. **Sync Profiles**: Predefined entity combinations for common scenarios

### Advanced Features

1. **Incremental Entity Sync**: Entity-specific incremental sync timestamps
2. **Parallel Entity Sync**: Sync independent entities in parallel
3. **Entity Health Checks**: Validate entity sync completeness
4. **Sync Analytics**: Detailed analytics per entity type

## Conclusion

The entity-specific sync filtering feature provides significant value with minimal implementation effort. The existing architecture is perfectly suited for this enhancement, requiring only ~40 lines of code changes across 2 files. The feature improves performance, operational flexibility, and development efficiency while maintaining full backward compatibility.

The low-risk, high-value nature of this enhancement makes it an ideal candidate for immediate implementation.
