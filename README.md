# Pydantic AI Okta Agent

An AI-powered Okta management tool that combines data synchronization with natural language querying capabilities.

## Overview

This tool provides:
1. Automated Okta data synchronization
2. Natural language querying of Okta data
3. Support for multiple AI providers (Vertex AI, OpenAI, Azure OpenAI, etc.)

## Prerequisites

- Python 3.12 or higher
- Access to an Okta developer instance
- Access to at least one of the supported AI providers:
  - Google Vertex AI
  - OpenAI
  - Azure OpenAI
  - OpenAI Compatible API (e.g., Fireworks)

## Installation

1. Clone the repo: 
```bash
git clone https://github.com/fctr-id/okta-ai-agent
```

2. Create a virtual environment:
```bash
python -m venv venv
.\venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Rename the `.env.sample` file in the project root to `.env` and update it with your configurations:
```ini
# Okta Configuration
OKTA_CLIENT_ORGURL=https://your-dev-instance.okta.com
OKTA_CLIENT_TOKEN=your-okta-api-token

# AI Provider Selection (vertex_ai, openai, azure_openai, openai_compatible)
AI_PROVIDER=vertex_ai

# Configure based on your chosen AI provider
# Example for Vertex AI:
VERTEX_AI_SERVICE_ACCOUNT_FILE=path/to/service-account.json
VERTEX_AI_REASONING_MODEL=gemini-1.5-pro
VERTEX_AI_CODING_MODEL=gemini-1.5-pro
```

## Pull Okta data into DB

1. Perform initial sync:
```bash
python Fetch_Okta_Data.py
```

## Query using AI 

1. Start the AI agent:
```bash
python Okta_AI_Agent.py
```

2. Ask questions in natural language, for example:
   - "List all active users"
   - "Show me a list of users assigned to application 'app-name'."
   - "Find all users that have PUSH registered"

## Important Notes

1. **Beta Version**: This is a beta release. Use in non-production environments only.
2. **Limited Fields** - Currently only fetching the login and email addresses from users' profile. No other attributes
3. **Data Security**: 
   - The tool stores data locally in SQLite
   - No data is sent to AI providers except query context
   - Use appropriate API tokens and credentials

4. **Limitations**:
   - Sync process is incremental but may take time for large organizations
   - AI responses depend on the chosen provider's capabilities
   - Some complex queries may require refinement

## Support

For issues or questions:
1. Check configuration in `.env`
2. Verify Okta API token permissions
3. Ensure AI provider credentials are correct
4. Check logs in `logs/` directory

## Legal Notice

Please refer to License.md file for licensing info

© 2024 Fctr .All rights reserved.