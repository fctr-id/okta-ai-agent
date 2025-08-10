# Version History



## Current latest: v1.1.1-beta (08-10-2025) - "Brain Boost"

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