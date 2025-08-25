# Version History


## Current latest: v1.2.0-beta (08-25-2025) - "Anchor Drop"

This release focuses on delivering consistent, deterministic results and transforming the user experience from guesswork to clarity. While acknowledging the probabilistic nature of LLMs, we've engineered systematic improvements through advanced context-engineering that dramatically reduce variability and provide complete visibility into execution processes.

Major Enhancements:
- **Relation Analysis Agent**: New agent delivers ~95% consistent multi-step result assembly by correlating cross-step entities (user ↔ device ↔ policy)
- **Expandable Execution Panel**: Replaced stepper with rich expansion panels showing status, timings, errors, and payload visibility with progressive disclosure
- **Memory Optimization Fix**: Eliminated execution manager duplicate in-memory dataset bug that was causing RAM bloat and removed mirrored variable references
- **Code Cleanup**: Removed inefficient variable handling logic and redundant frontend utilities

Performance & Reliability:
- **Normalized Relationships**: Structured linkage reduces missed joins and result drift
- **Enhanced Context**: Internal naming rationalized for relation analysis logic consistency

## v1.1.4-beta (08-14-2025) - "Bug Buster"

Major Bugs Fixed: (update immediately)
- **Fixed API Response Correlation**: Resolved critical issue with API responses failing SQL co-relation that was preventing proper data joins (appreciate all of you who worked with us on this)
- **Fixed Results Formatter Sampling**: Completely rewrote sampling logic to handle Modern Execution Manager's NEW data structure, eliminating token overflow errors (thanks again here!)
- **Fixed Sample Data Key Names**: Corrected sample data structure to include proper step key names (`1_api`, `2_api`, etc.) instead of sending anonymous sample sets

UI Updates:
- **Enhanced Step Clarity**: The stepper now displays entity name along with operation name for improved execution visibility

Framework Improvements:
- **Intelligent Sampling**: Implemented per-step sampling with data simplification for large datasets
- **Token Optimization**: Reduced sample prompts from 698k to ~17k characters through aggressive data truncation
- **Environment Configuration**: Updated .env.sample file with current model names across all AI providers for better setup guidance

Community Contributions:
- **AWS Session Token Support**: Added support for AWS session tokens in Bedrock configuration for enhanced security with temporary credentials and STS assume role scenarios ([PR #12](https://github.com/fctr-id/okta-ai-agent/pull/12) - Thanks @Kittzus!)


## v1.1.3-beta (08-12-2025) - "Octo Morph"

Major Framework & Intelligence Upgrades:
- **ARM64 Support**: Migrated from polars to polars-lts-cpu for enhanced ARM64/Apple Silicon compatibility
- **New Okta EventTypes Tool**: Added sophisticated event type selection tool for precise Okta system log filtering
- **Multi-Provider AI Testing**: Extensively tested prompts across multiple AI providers (OpenAI, Anthropic, Google) for consistent results
- **Model Compatibility Verification**: Updated and validated AI model configurations across providers


Framework & Encoding Fixes:
- **PydanticAI v0.6.2 Migration**: Successfully upgraded from v0.4.11 to v0.6.2 with full breaking changes compatibility
- **Python Package Updates**- Updated all python packaages to the latest versions
- **Deprecated API Cleanup**: Removed GoogleVertexProvider, migrated result_type→output_type, updated .data→.output properties
- **Windows Unicode Support**: Fixed Windows cp1252 encoding issues preventing server startup with Unicode characters
- **Emoji Cleanup**: Removed Unicode emojis from code comments to prevent Windows encoding conflicts
- **Subprocess Encoding**: Added UTF-8 encoding with error handling for cross-platform compatibility

Previous Updates:

## v1.1.2-beta (08-10-2025) - "API Etiquette School"

API Code Generation & Rate Limiting Enhancements:
- **MAX LIMIT RULE Implementation**: API Code Generation Agent now properly handles `max_results` parameter when users request specific quantities
- **Configurable Concurrent Limits**: Added `API_CODE_CONCURRENT_LIMIT` environment variable with intelligent defaults based on Okta plan types
- **Race Condition Prevention**: Implemented random jitter for concurrent rate limit retries to prevent API conflicts
- **Enhanced Security**: Strengthened variable access patterns in generated code - direct variable access only, no `globals()` usage
- **Performance Optimization**: Reduced inter-chunk delays from 0.5s to 0.1s while maintaining API stability

Documentation & Configuration Updates:
- **Corrected Okta Rate Limits**: Updated README with accurate concurrent transaction limits per Okta plan type
- **Settings Class Integration**: Enhanced base API client to use centralized Settings class with proper fallbacks


Critical Fixes:
- **Concurrent Rate Limit Handling**: Distinguished between concurrent vs org-wide rate limits with appropriate retry strategies
- **API Client Architecture**: Proper Settings class integration ensuring consistent configuration loading
- **Code Generation Security**: Eliminated unsafe variable access patterns in generated Python code

## v1.1.1-beta (08-10-2025) - "Brain Boost"

Agent Intelligence & Prompt Engineering Enhancements:
- **Enhanced Field Value Translation**: Improved SQL agents' schema-grounded translation of user-friendly terms (e.g., "fastpass" → "signed_nonce") 
- **Multi-Agent Prompt Optimization**: Refined system prompts with structured 3-step validation workflows (IDENTIFY → VALIDATE → TRANSLATE)
- **Schema-Aware Query Generation**: Strengthened agent grounding to prioritize database schema truth over planning context assumptions
- **Smart Results Formatting Logic**: Enhanced results formatter with intelligent bypass detection for aggregation queries
- **Entity-Operation Mapping Fixes**: Corrected planning agent to use exact endpoint definitions instead of inferring from operation names

Performance & Reliability Improvements:
- **API Client Optimizations**: Enhanced concurrent request limits for improved API throughput and rate limit handling
- **Results Formatter Intelligence**: Modified formatting logic to better detect when grouping/aggregation is needed vs simple table display
- **Legacy SQL Agent Updates**: Minor improvements to SQL generation patterns and error handling

## v1.1-beta (08-08-2025) - "Tentacle Tuning"

Enhancements:
- Introduced advanced strategy agent for enhanced query planning and execution step optimization
- Redesigned stepper interface with improved user experience and visual progress tracking
- Implemented high-performance streaming architecture delivering 5x faster results processing
- Enhanced contextual intelligence providing comprehensive entity details across all query types
- Added intelligent data source indicators distinguishing between database, real-time API, and hybrid operations
- Refined user interface terminology with professional AI-focused language throughout execution flow
- Multi-architecture Docker support for both AMD64 and ARM64 platforms (Apple Silicon, AWS Graviton)

Fixes:
- Resolved frontend rendering issues affecting batch streaming result display
- Addressed critical ReDOS security vulnerability identified through CodeQL static analysis
- Corrected Azure OpenAI configuration variables in model selection framework
- Fixed hybrid query detection logic ensuring accurate API+SQL step combination identification
- Improved stepper component handling for mixed-mode database and API operations

Maintenance:
- Removed deprecated openai_compatible.py module
- Streamlined data source detection architecture for improved system maintainability

## v1.0-beta (08-06-2025) - "Kraken Unleashed"

Revolutionary Multi-Agent Architecture:
- 5 specialized agents working in perfect coordination
- Context-engineered communication for optimal performance
- 99% token reduction through intelligent context filtering

API-Only Operation Mode:
- NEW: Complete operation without database sync
- 107+ Okta GET endpoints with automatic code generation
- Real-time data access - choose hybrid or pure API-only mode

Enhanced AI Provider Support:
- Google Vertex AI, OpenAI, Azure OpenAI, Anthropic, AWS Bedrock, Ollama
- Dual model architecture for reasoning + coding optimization

Breaking Changes:
- Complete architectural rewrite - not compatible with v0.6.x
- New environment variables required for multi-agent setup
- Updated Docker configuration - follow new installation guide

Migration from v0.6.x:
- Backup existing data if needed
- Follow new installation process for setup
- Configure new environment variables
- Legacy documentation available for previous architecture

## v0.6.1-beta (07-13-2025) - "Speedy Sucker"

- Support for new user attribute statusChanged
- Huge performance imporvements for SQL (removed JSON_EXTRACT)

## v0.5.5-beta (2025-06-12) - "Device Detective"
Custom User Attributes & Device Management:
- Added comprehensive custom user attributes support with JSON storage and querying
- Implemented full Okta device synchronization with user-device relationships
- Added device security context tracking (management status, screen locks, hardware features)
- Enhanced UI with conditional device/policy display based on sync configuration
- Improved SQL schema documentation for device and custom attribute queries
- Fixed sync order dependencies to ensure proper user-device relationship creation
- Added device analytics capabilities for platform, manufacturer, and security queries
- Support for self-signed and internal CA certificates for openai_compatible provider
- Update pydantic AI framework to the latest version
- Bug fixes and minor performance improvements

## v0.5.0-beta (2025-05-20) - "Realtime Reach"
Realtime Agents!
- New user interface for realtime queries
- Command line srcipt to use similar to MCP servers wihout context limitations
- Added Anthropic as another AI provider
- Custom headers if using LLM proxy or other security proxies
- Pydantic_ai update to 0.1.10
- Much better optimization API-DB sync process
- Clean logging without rate limit errors
- Many more bug fixes and imporvements.


## v0.3.5-beta (2025-03-26) - "Attribute Antics"
- Added new user attributes -  country_code, userType, Title, organization, password_changed_at
- Added multiple new indexex to speed up queries
- Tweaks both to reasoning and coding agents to get better outputs from the LLMs
- Multiple bugfixes and improvements

## v0.3.0-beta (2025-03-23) - "Sync Surge"
- Resolved multiple critical bugs in the data synchronization pipeline
- Significantly enhanced Okta-to-DB synchronization performance and efficiency
- Implemented user interface refinements for improved usability

## v0.2.0-beta (2025-03-09) - "Interface Ink"
Web Interface: Modern, responsive UI for better query experience
Fast API and Vue JS
Docker Support: Easy deployment with containerization
Enhanced Security: Mandatory HTTPS with improved security headers
Improved Sync Performance: Faster data synchronization with parallel processing
Database Optimization: Automatic cleanup of sync history to maintain optimal size
CSV Export: Export query results to CSV files
