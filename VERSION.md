# Version History

## Current Latest: v0.5.0-beta (2025-05-20)
Realtime Agents!
  _ new user interface for realtime queries
  _ Command line srcipt to use similar to MCP servers wihout context limitations
Added Anthropic as another AI provider
Custom headers if using LLM proxy or other security proxies
Pydantic_ai update to 0.1.10
Much better optimization API-DB sync process
Clean logging without rate limit errors
Many more bug fixes and imporvements.


## Current Latest: v0.3.5-beta (2025-03-26)
- Added new user attributes -  country_code, userType, Title, organization, password_changed_at
- Added multiple new indexex to speed up queries
- Tweaks both to reasoning and coding agents to get better outputs from the LLMs
- Multiple bugfixes and improvements

## Current Latest: v0.3.0-beta (2025-03-23)
- Resolved multiple critical bugs in the data synchronization pipeline
- Significantly enhanced Okta-to-DB synchronization performance and efficiency
- Implemented user interface refinements for improved usability

## v0.2.0-beta (2025-03-09)
Web Interface: Modern, responsive UI for better query experience
Fast API and Vue JS
Docker Support: Easy deployment with containerization
Enhanced Security: Mandatory HTTPS with improved security headers
Improved Sync Performance: Faster data synchronization with parallel processing
Database Optimization: Automatic cleanup of sync history to maintain optimal size
CSV Export: Export query results to CSV files