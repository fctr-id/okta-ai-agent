<p align="center">
  <a href="https://fctr.io">
    <img src="https://fctr.io/images/logo.svg" alt="fctr.io" width="110" height="auto">
  </a>
</p>

<h1 style="margin-top: -6px" align="center">AI Agent for Okta</h1>

This AI agent lets you use natural language to query your Okta tenant's details. Built for admins, powered by enterprise AI models.

## 📑 Index
- [📑 Index](#-index)
- [✨ What's Special?](#-whats-special)
- [🚀 Quick Start](#-quick-start)
  - [Prerequisites](#prerequisites)
  - [Get Started in Minutes!](#get-started-in-minutes)
- [🎯 Usage](#-usage)
- [🛡️ Security \& Privacy](#️-security--privacy)
  - [Data Control](#data-control)
  - [Data Privacy (as of Feb 15th, 2025)](#data-privacy-as-of-feb-15th-2025)
  - [Data Model Overview (as of Feb 15th, 2025)](#data-model-overview-as-of-feb-15th-2025)
- [⚠️ Good to Know](#️-good-to-know)
  - [Beta Release 🧪](#beta-release-)
  - [Security First 🛡️](#security-first-️)
  - [Current Boundaries 🎯](#current-boundaries-)
- [🆘 Need Help?](#-need-help)
- [⚖️ Legal Stuff](#️-legal-stuff)

## ✨ What's Special?

This  tool brings you:
* 🚀 **Easy Okta Sync** - Quick and parallel okta sync to local SQLlite DB
* 💡 **Natural Language Queries** - Talk to your Okta data in simple english
*  ⚡ **Multiple AI Providers** - Leverage the power of leading AI providers:
     -  Google Vertex AI (Gemini 1.5 Pro)
     -  OpenAI (GPT-4)
     -  Azure OpenAI (GPT-4)
     -  Ollama (Local, Self-hosted, use 32B+ models)
     -  OpenAI Compatible APIs (Fireworks, Together AI, OpenRouter ...etc)
  

## 🚀 Quick Start

### Prerequisites
* Python 3.12+
* Okta tenant superadmin acess
* Access to any supported AI provider mentioned above

### Get Started in Minutes!

1. **Clone & Navigate**
```bash
git clone https://github.com/fctr-id/okta-ai-agent
cd okta-ai-agent
```

2. **Set Up Your Python Virtual Environment**
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

3. **Configure Your .env file** (`.env`)
```bash
cp .env.sample .env
```
Modify these as needed
```ini
# 🔐 Okta Configuration
OKTA_CLIENT_ORGURL=https://your-dev-instance.okta.com
OKTA_CLIENT_TOKEN=your-okta-api-token

# 🧠 AI Settings
AI_PROVIDER=vertex_ai
USE_PRE_REASONING=True

# 🌐 Vertex AI Configuration
VERTEX_AI_SERVICE_ACCOUNT_FILE=path/to/service-account.json
VERTEX_AI_REASONING_MODEL=gemini-1.5-pro
VERTEX_AI_CODING_MODEL=gemini-1.5-pro
```

## 🎯 Usage

1. **Sync Your Data**
```bash
python Fetch_Okta_Data.py
```

2. **Start the AI Magic**
```bash
python Okta_AI_Agent.py
```

3. **Ask Away!** Try these cool queries:
* 👥 "Who are my active users?"
* 🎯 "Show me users in the 'Sales' application"
* 📱 "List everyone with PUSH authentication"  


## 🛡️ Security & Privacy 

### Data Control
- **Local Storage**: All Okta data is stored in SQLite DB - a file-based database that lives entirely on your PC/VM
- **Your Token, Your Rules**: You create and control the Okta API token, including restricting its network access and role permissions
- **LLM Flexibility**: 
  - Use your enterprise-approved AI providers
  - Deploy Ollama locally for a completely local environment
  - Full control over model selection  

### Data Privacy (as of Feb 15th, 2025)
- ✅ **What's Sent to LLMs**:
  - User queries (user prompts)
  - System prompts 
- ❌ **What's Not Sent**:
  - No Okta user data
  - No organizational data
  - No synced database contents

> **Note**: Future relases may introduce features that will require the Okta data to be sent to the LLM for summarization.
>  Any such changes will be clearly documented in release notes.

### Data Model Overview (as of Feb 15th, 2025)

| Entity | Core Fields |
|--------|------------|
| Users | `email`, `login`, `first_name`, `last_name`, `status` |
| Groups | `name`, `description` |
| Applications | `name`, `label`, `status`, `sign_on_mode` |
| Factors | `factor_type`, `provider`, `status`, `device_type` |
| Policies | `name`, `description`, `status`, `type` |

The relationship data for users -> factors, users -> groups, users -> applications 

Each entity includes: `tenant_id`, `okta_id`, `created_at`, `updated_at`

> **Note**: You can view the data saved to your SqlLite DB using tools like [DB Browser for SQLite](https://github.com/sqlitebrowser/sqlitebrowser).




## ⚠️ Good to Know

### Beta Release 🧪
* Testing grounds - keep it out of production!
* Currently focusing on core user fields
* Large orgs might need a coffee break during sync

### Security First 🛡️
* Data lives safely in your local SQLite
* AI sees only what it needs to
* Proper token hygiene required

### Current Boundaries 🎯
* AI responses vary by provider
* Complex questions might need simplifying
* One tenant at a time

## 🆘 Need Help?

Before raising an issue, check:
1. 📝 `.env` configuration
2. 🔑 Okta API permissions
3. 🤖 AI provider setup
4. 📊 `logs` directory

Still having problems? Open an issue on GitHub or email support@fctr.io (response times may vary)


## ⚖️ Legal Stuff

Check out [`License.md`](License.md) for the fine print.

---

🌟 © 2024 Fctr. All rights reserved. Made with ❤️ for the Okta community.