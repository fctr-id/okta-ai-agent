<div align="center">
  <a href="https://fctr.io">
    <img src="https://fctr.io/images/logo.svg" alt="fctr.io" width="110" height="auto">
  </a>
</div>

<h2 style="margin-left: 10px" align="center">AI Agent for Okta (BETA)</h2>

This AI agent is the first of it's kind that lets you use natural language to query your Okta tenant's details. Built for admins, IAM managers. IT GRC teams and audit teams, powered by enterprise AI models.

- [✨ What's Special?](#-whats-special)
- [🚀 Quick Start](#-quick-start)
  - [Prerequisites](#prerequisites)
  - [Get Started](#get-started)
  - [🎯 Usage](#-usage)
  - [Usage Examples \& Community Queries](#usage-examples--community-queries)
  - [Share Your Queries!](#share-your-queries)
- [🛡️ Security \& Privacy](#️-security--privacy)
  - [Data Control](#data-control)
  - [Data Privacy](#data-privacy)
  - [Data Model Overview](#data-model-overview)
- [⚠️ Good to Know](#️-good-to-know)
  - [Beta Release 🧪](#beta-release-)
  - [Security First 🛡️](#security-first-️)
  - [Current Limitations 🔍](#current-limitations-)
- [🗺️ Roadmap](#️-roadmap)
  - [Real-time Data Integration](#real-time-data-integration)
  - [Event Log Analytics](#event-log-analytics)
  - [Managed Changes](#managed-changes)
- [🆘 Need Help?](#-need-help)
- [💡 Feature Requests \& Ideas](#-feature-requests--ideas)
- [👥 Contributors](#-contributors)
- [⚖️ Legal Stuff](#️-legal-stuff)

&nbsp;

## ✨ What's Special?

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

### Get Started

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

### 🎯 Usage

1. **Sync Your Data**
```bash
python Fetch_Okta_Data.py
```

2. **Start the AI Magic**
```bash
python Okta_AI_Agent.py
```

### Usage Examples & Community Queries

Try these example queries to get started:

* 👥 "Who are my active users?"
* 🎯 "Show me users in the 'Sales' application"
* 📱 "List everyone with PUSH authentication"

### Share Your Queries!

We're building a community knowledge base! Explore and contribute:

| Action | Link |
|--------|------|
| 📝 Submit Query | [Share your examples](https://messy-heath-9e9.notion.site/19cc111b8adc80f9889bdc9badf1ee89?pvs=105) |
| 🔍 View Examples | [Browse community queries](https://messy-heath-9e9.notion.site/19cc111b8adc80718a40e59d1c41b30f?v=19cc111b8adc8013b94e000ce7e23638&pvs=4) |


## 🛡️ Security & Privacy 

<p align="center">
  <img src="docs/okta_ai_agent_architecture.png" alt="Okta AI Agent Demo" width="800" height="auto">
</p>


### Data Control
- **Local Storage**: All Okta data is stored in SQLite DB - a file-based database that lives entirely on your PC/VM
- **Your Token, Your Rules**: You create and control the Okta API token, including restricting its network access and role permissions
- **LLM Flexibility**: 
  - Use your enterprise-approved AI providers
  - Deploy Ollama locally for a completely local environment
  - Full control over model selection  


### Data Privacy 

- ✅ **What's Sent to LLMs**:
  - User queries (user prompts)
  - System prompts 
- ❌ **What's Not Sent**:
  - No Okta user data
  - No organizational data
  - No synced database contents
  

⚠️ **Future Features Notice** ⚠️

Future releases may introduce optional features that require sending Okta data to LLMs for summarization.
All such changes will be clearly documented in release notes.

### Data Model Overview 

| Entity | Core Fields |
|--------|-------------|
| Users | `email`, `login`, `first_name`, `last_name`, `status`, `mobile_phone`, `primary_phone`, `employee_number`, `department`, `manager` |
| Groups | `name`, `description` |
| Applications | `name`, `label`, `status`, `sign_on_mode`, `metadata_url`, `sign_on_url`, `audience`, `destination`, `signing_kid`, `username_template`, `username_template_type`, `admin_note`, `attribute_statements`, `honor_force_authn`, `hide_ios`, `hide_web`, `policy_id`, `settings`, `features`, `visibility`, `credentials`, `licensing`, `embedded_url`, `accessibility`, `user_name_template`, `app_settings`, `app_embedded_url` |
| UserFactors | `factor_type`, `provider`, `status`, `email`, `phone_number`, `device_type`, `device_name`, `platform` |
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
* AI/LLM sees only what it needs to
* Proper token hygiene required

### Current Limitations 🔍
* The responses are stateless, i.e., every query is answered as is asked without any relevance to the previous queries / responses.
* Tested on Identity engine only
* AI responses vary by provider
* Complex questions might need simplifying
* One tenant at a time

## 🗺️ Roadmap

### Real-time Data Integration
- [ ] Work with real time data / APIs
  - Profile, factors & last week's activity summary
  - User summary
  - Risk indicators

### Event Log Analytics
- [ ] System Log Queries
  - Failed logins, MFA events, admin actions
  - Anomaly detection
  - Custom reports

### Managed Changes
- [ ] Change Management with Approvals
  - Group memberships
  - Policy modifications
  - App assignments

## 🆘 Need Help?

Before raising an issue, check:
1. 📝 `.env` configuration
2. 🔑 Okta API permissions
3. 🤖 AI provider setup
4. 📊 `logs` directory

Still having problems? Open an issue on GitHub or email support@fctr.io (response times may vary)

## 💡 Feature Requests & Ideas

Have an idea or suggestion? [Open a feature request](https://github.com/fctr-id/okta-ai-agent/issues/new?labels=enhancement) on GitHub!

## 👥 Contributors

Interested in contributing? We'd love to have you! Reach out to dan@fctr.io

## ⚖️ Legal Stuff

Check out [`License.md`](License.md) for the fine print.

---

🌟 © 2024 Fctr. All rights reserved. Made with ❤️ for the Okta community.
