<div align="center">
  <a href="https://fctr.io">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./media/brand/fctr-lockup-reverse.svg">
      <source media="(prefers-color-scheme: light)" srcset="./media/brand/fctr-lockup-primary.svg">
      <img src="./media/brand/fctr-lockup-primary.svg" alt="Fctr" width="96">
    </picture>
  </a>

  <br>

  <h1>Tako AI Agent for Okta</h1>

  <p>
    <a href="#quick-start-docker">Quick start</a> ·
    <a href="#why-tako">Why Tako</a> ·
    <a href="#demo">Demo</a> ·
    <a href="#ai-provider-support">AI providers</a> ·
    <a href="#documentation--support">Docs &amp; support</a>
  </p>

  <p>
    <a href="VERSION.md">
      <img src="./media/badges/preview.svg" alt="Preview: v3.0.1-beta" width="136" height="22">
    </a>
    <a href="docker-compose.yml">
      <img src="./media/badges/docker.svg" alt="Docker: AMD64 and ARM64" width="144" height="22">
    </a>
    <a href="https://python.org">
      <img src="./media/badges/python.svg" alt="Python 3.11+" width="88" height="22">
    </a>
  </p>

  <p>Built by the Fctr Identity team · Not affiliated with Okta</p>
</div>

---

Tako is a self-hosted AI assistant for querying and analyzing your Okta tenant in plain English. Ask about users, groups, applications, and access; inspect the results, ask follow-up questions, and export data or reusable scripts.

## Why Tako?

Most capable LLMs can answer Okta questions with the right tools and data.

Tako’s harness is built specifically for accurate Okta answers with:

- Fewer tokens
- Less time
- Lower cost

It supplies Okta-specific context, tests retrieval queries, and reuses earlier results to reduce repeated discovery and trial and error.

| Harness capability | How it helps |
|---|---|
| Okta-specific context | Supplies API definitions, database schemas, and query guidance to reduce endpoint and parameter guesswork. |
| Targeted data access | Routes requests to synced SQL data, live APIs, or specialist tools according to the question and available evidence. |
| Compact model context | Passes result references, metadata, and small samples between agents; uses code to process larger datasets. |
| Tested retrieval | Tests discovery queries and API code before synthesis, with request and retry limits to bound repeated attempts. |
| Result reuse | Builds follow-ups on saved results and retrieves missing information, reducing repeated discovery. |

The goal is accurate Okta answers with fewer exploratory calls, fewer tokens, and less waiting. Results and savings vary by model, question, tenant size, and data freshness.

<details>
<summary>How the agents work</summary>

| Agent | Role |
|---|---|
| Supervisor | Chooses the next specialist and decides when the request is complete. |
| SQL Discovery | Retrieves evidence from the synced SQLite database. |
| API Discovery | Retrieves live data for API-only requests, missing fields, or freshness requirements. |
| Special Tools | Runs supported access-analysis and login-risk workflows. |
| Result Analysis | Analyzes saved results and preserves the scope of follow-up questions. |
| Synthesis | Uses tested retrieval artifacts to produce the final answer or script. |

</details>

### Data access

- API mode — Query live Okta data without an initial database sync.
- Database mode — Sync supported entities to local SQLite for SQL queries.
- Hybrid mode — Combine synced data with live API results when needed.

## Demo

https://github.com/user-attachments/assets/7a27ebc4-39a0-400f-bf16-505afca7ca3d

*Query discovery, execution progress, and CSV export. Recorded before the current visual redesign.*

### Try questions like

- "List active users in Engineering with no MFA enrolled."
- "Show the roles for those users." — a follow-up using the previous result set
- "Find the SAML certificate expiry date for all active SAML applications."

## Features

- Conversation and follow-ups — Build on saved results within a session.
- Visible progress — Inspect discovery, execution, tables, and generated scripts.
- History and favorites — Revisit recent queries and save frequent ones.
- CSV and Python export — Take results into reports or reuse scripts with Tako's runtime dependencies.
- CLI automation — Run queries and database syncs from scheduled jobs.
- Optional Slack bot — Query your tenant with `/tako`; disabled by default.
- Docker deployment — Self-host on AMD64 or ARM64 with your chosen AI provider.

### What's new

The v3 harness adds supervisor-led routing and persistent multi-turn results. See [version history](VERSION.md) for release details and the v3.0.1-beta security patch.

> [!NOTE]
> UI redesign in progress. A refreshed visual design with more polished typography, spacing, tables, and progress displays. The existing workflows and sections stay the same.

## Quick Start (Docker)

For a local installation without Docker, see the [installation guide](https://github.com/fctr-id/okta-ai-agent/wiki/Installation).

### Prerequisites

- Docker with Docker Compose.
- An Okta Identity Engine tenant with [OAuth 2.0 or API token authentication configured](https://github.com/fctr-id/okta-ai-agent/wiki/Authentication-&-Authorization-%E2%80%90-Oauth-2-and-API-tokens).
- Access to a [supported AI provider](#ai-provider-support).

### Installation

Docker images support AMD64 (Intel/AMD) and ARM64 (Apple Silicon, AWS Graviton).

Choose your operating system:

<details>
<summary>Linux / macOS</summary>

```bash
# 1. Create a project directory and navigate to it
mkdir okta-ai-agent 
cd okta-ai-agent

# 2. Create required directories for data persistence
mkdir -p sqlite_db chat_sessions logs certs

# (Optional) Place your own TLS cert/key as certs/cert.pem and certs/key.pem for custom HTTPS

# 3. Download the docker-compose.yml file
curl -O https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/docker-compose.yml

# 4. Download and modify the .env file with your configuration
curl -O https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/.env.sample
mv .env.sample .env

# Edit .env with your authentication, AI provider, and rate-limit settings.
# nano .env (or use your favorite editor)
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
# 1. Create a project directory and navigate to it
New-Item -ItemType Directory -Path okta-ai-agent
Set-Location okta-ai-agent

# 2. Create required directories for data persistence
New-Item -ItemType Directory -Path sqlite_db, chat_sessions, logs, certs -Force

# (Optional) Place your own TLS cert.pem and key.pem files in the certs directory for custom HTTPS

# 3. Download the docker-compose.yml file
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/docker-compose.yml" -OutFile "docker-compose.yml"

# 4. Download and modify the .env file with your configuration
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/.env.sample" -OutFile ".env.sample"
Rename-Item -Path ".env.sample" -NewName ".env"

# Edit .env with your authentication, AI provider, and rate-limit settings.
# notepad .env (or use your favorite editor)
```

</details>

### Configure rate limits

Set `OKTA_CONCURRENT_LIMIT` in your `.env` for the capacity available to Tako. Account for your tenant's limits, token or OAuth app allocation, and other integrations sharing the tenant.

Concurrent requests and requests per minute are separate limits. Use your Okta rate-limit dashboard and the current [rate-limit](https://developer.okta.com/docs/reference/rate-limits/) and [concurrency](https://developer.okta.com/docs/reference/rl2-concurrency/) documentation when choosing a value. If syncs repeatedly hit rate limits, reduce concurrency and retry.

### Launch Application

After configuring authentication, your AI provider, and rate limits:

```bash
# Start Tako
docker compose up -d

# View logs
docker compose logs -f
```

Open [https://localhost:8001](https://localhost:8001).

> First-run setup: When no admin account exists yet, Tako prints a one-time setup token in the startup logs. Use that token on the setup screen to create the initial admin account.

## CLI Tools for Automation

Use the CLI for scheduled reports, data syncs, and reusable scripts after completing setup.

Tako CLI (`tako-cli.py`)

Local Installation:
```bash
# Run queries from command line
python scripts/tako-cli.py "list all users created in last 30 days"

# Generate reusable scripts
python scripts/tako-cli.py "show suspended users" --scriptonly

# Export results as CSV
python scripts/tako-cli.py "find users with MFA enabled" --csv
```

Docker Installation:
```bash
# Run queries from command line
docker exec okta-ai-agent python scripts/tako-cli.py "list all users created in last 30 days"

# Generate reusable scripts
docker exec okta-ai-agent python scripts/tako-cli.py "show suspended users" --scriptonly

# Export results as CSV
docker exec okta-ai-agent python scripts/tako-cli.py "find users with MFA enabled" --csv
```

> Note: The ".env file not found" warning when using `docker exec` is harmless - environment variables are already loaded by docker-compose.

Sync CLI (`sync_okta_to_db.py`)

Local Installation:
```bash
# Scheduled database sync for automation
python scripts/sync_okta_to_db.py
```

Docker Installation:
```bash
docker exec okta-ai-agent python scripts/sync_okta_to_db.py
```

Generated scripts use Tako's runtime dependencies and configuration.

## Slack Bot Integration

Allowlisted users can query the configured Okta tenant from Slack.

The bot is disabled by default. Set `ENABLE_SLACK_BOT=true` in your `.env` and complete the [Slack setup guide](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Slack-Bot-Setup-&-Testing-Guide).

### Available Commands

```
/tako [question]   → ask anything about your Okta tenant in plain English
/tako sync         → trigger a full Okta data sync
/tako status       → check database health and last sync time
/tako history      → your last 5 queries with ▶ Run and ☆ Star buttons
/tako favorites    → your starred queries, always one click away
/tako help         → full command reference
```

### Security Highlights

- Allowlist access — configure `SLACK_ALLOWED_EMAILS` or `SLACK_ALLOWED_GROUPS` to grant access
- Socket Mode — opens an outbound WebSocket to Slack, no public URL or port-forwarding required
- Per-action authorization — access is checked for slash commands and button actions

---

## Migration Notes

If you are upgrading from v1.x to any v2.x or v3.x build, the v2.0 database recreation step still applies:

```bash
# 1. Stop the running container
docker compose down

# 2. Delete the existing database
rm sqlite_db/okta_sync.db   # Linux/macOS
# OR
Remove-Item sqlite_db\okta_sync.db  # Windows PowerShell

# 3. Pull the latest image and restart
docker compose pull
docker compose up -d

# 4. Navigate to the UI and run a full sync
# https://localhost:8001 → Click "Sync" button
```

The v2.0 schema changed application assignments to include group attribution and assignment metadata. A full resync rebuilds those relationships. See [version history](VERSION.md) for other release-specific changes.

## Featured Articles & Videos

- [📚 Tako AI v2.0: The Swarm is Here](https://iamse.blog/2026/01/30/tako-ai-v2-0-the-swarm-is-here/)
- [📚 How Tako AI v1.1 Delivers Where Other Okta Tools Fall Short](https://iamse.blog/2025/08/07/tako-ai-v1-0-for-everyone-who-thought-ai-for-okta-was-just-hype/)
- [🎥 Installation and Demo Video](https://www.youtube.com/watch?v=PC8arYq5kZk)

## AI Provider Support

Tako supports OpenAI, Google AI Studio, Google Vertex AI, Anthropic, Azure OpenAI, AWS Bedrock, and OpenAI-compatible endpoints, including local deployments such as Ollama.

Configure separate models for code generation and reasoning to fit your workload and budget. Model choice affects query quality, response time, and cost.

<details>
<summary>Previously tested models</summary>

The following models are recorded in the project's testing history. Validate your chosen configuration with representative Okta questions.

Code generation

- Claude Haiku 4.5
- Gemini 3 Flash
- GPT-5.4 mini
- Claude Sonnet 4
- Gemini 2.5 Pro
- OpenAI GPT-OSS 120B

Reasoning and tool summarization

- GPT-5.4
- OpenAI GPT-OSS 120B
- Claude Sonnet 4.6
- Gemini 3 Pro
- Gemini 2.5 Pro
- o3
- GPT-5 mini

</details>

## Security & Privacy

### Authentication and authorization

- OAuth 2.0 or API tokens — Queries use the permissions granted to your configured Okta credentials. Configure least-privilege read access for the data you need.
- Initial admin setup — A one-time setup token gates creation of the first application admin account.
- Optional Slack access — Explicit user or group allowlists control access to the bot.

<details>
<summary>Additional permissions for role and policy queries</summary>

Queries such as enumerating admin role assignments may require permissions beyond Okta's basic read-only administrator role.

1. Create a custom role with: "View roles, resources, and admin assignments"
2. Set resources to: "All Identity and Access Management resources"
3. Assign this custom role in addition to your existing READ-ONLY administrator role

</details>

### Data and execution

- Self-hosted storage — Synced data, saved conversation results, and logs are stored on your infrastructure.
- AI provider processing — Prompts can include Okta data, query samples, and result context. When you select a cloud AI provider, that content is sent to the provider.
- Local inference option — Use a compatible local model endpoint to keep model inference on your infrastructure. Tako still needs connectivity to your Okta tenant.
- Execution controls — Generated code is subject to validation and runtime limits.

### Database Schema

When using Database Mode, Tako syncs these entities to local SQLite:

<details>
<summary>Synced entities and fields</summary>

| Entity | Core Fields |
|------------|-----------------|
| Users | id, okta_id, email, login, first_name, last_name, status, mobile_phone, primary_phone, employee_number, department, manager, password_changed_at, status_changed_at, user_type, country_code, title, organization, custom_attributes, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| Groups | id, okta_id, name, description, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| Applications | id, okta_id, name, label, status, sign_on_mode, metadata_url, policy_id, sign_on_url, audience, destination, signing_kid, username_template, username_template_type, implicit_assignment, admin_note, attribute_statements, honor_force_authn, hide_ios, hide_web, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| Policies | id, okta_id, name, description, status, type, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| Devices | id, okta_id, status, display_name, platform, manufacturer, model, os_version, registered, secure_hardware_present, disk_encryption_type, serial_number, udid, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| UserDevices | id, user_okta_id, device_okta_id, management_status, screen_lock_type, user_device_created_at, created_at, last_updated_at, updated_at, last_synced_at, is_deleted |
| UserFactors | id, okta_id, user_okta_id, factor_type, provider, status, authenticator_name, email, phone_number, device_type, device_name, platform, created_at, last_updated_at, last_synced_at, updated_at, is_deleted |
| UserApplicationAssignments | user_okta_id, application_okta_id, assignment_id, assignment_type, group_name, group_okta_id, assignment_status, credentials_setup, hidden, created_at, updated_at |
| GroupApplicationAssignments | group_okta_id, application_okta_id, assignment_id, created_at, updated_at |
| UserGroupMemberships | user_okta_id, group_okta_id, created_at, updated_at |

Note: You can view the synced data using tools like DB Browser for SQLite.

</details>

## Documentation & Support

### Documentation

| Guide | What it covers |
|---|---|
| [Installation](https://github.com/fctr-id/okta-ai-agent/wiki/Installation) | Local setup and alternatives to Docker. |
| [Authentication](https://github.com/fctr-id/okta-ai-agent/wiki/Authentication-&-Authorization-%E2%80%90-Oauth-2-and-API-tokens) | OAuth 2.0, API tokens, and Okta permissions. |
| [Slack bot](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Slack-Bot-Setup-&-Testing-Guide) | Bot configuration, access, and testing. |
| [Supported endpoints](https://github.com/fctr-id/okta-ai-agent/wiki/Tako:-Supported-Okta-API-Endpoints) | Okta API coverage. |
| [Version history](VERSION.md) | Releases, migrations, and security fixes. |

### Current Status

- Preview release - Not for production use
- Requirements - Okta Identity Engine, single tenant
- Note - Large tenants may see longer initial sync times in Database Mode

### Get Help

Before opening an issue, check your configuration, Okta permissions, AI provider setup, and application logs. Include reproduction steps and redacted errors; keep credentials and tenant data out of issue reports.

Support Channels:

- 🐛 [GitHub Issues](https://github.com/fctr-id/okta-ai-agent/issues) - Bug reports and feature requests
- 📧 Email: support@fctr.io - General support  
- 💬 Slack: dan@fctr.io - Quick support

---

⭐ Found Tako helpful? [Star this repo](https://github.com/fctr-id/okta-ai-agent) to help other Okta admins discover it!

### Feature Requests & Ideas

- Have an enhancement in mind? [Open a feature request](https://github.com/fctr-id/okta-ai-agent/issues/new?labels=enhancement) and describe the use case.
- Clearly state data entities & outcome expected—this shortens triage time.


## Contributing

Interested in contributing? We'd love your help! Reach out to dan@fctr.io

## Star History

<details>
<summary>View the star history chart</summary>

[![Star History Chart](https://api.star-history.com/svg?repos=fctr-id/okta-ai-agent&type=Date)](https://star-history.com/#fctr-id/okta-ai-agent&Date)

</details>

## Contributors

<a href="https://github.com/fctr-id/okta-ai-agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=fctr-id/okta-ai-agent" alt="Tako contributors" />
</a>

## License

See [LICENSE](LICENSE) for details.

---

🌟 © 2025 Fctr. All rights reserved. Meet Tako, made with ❤️ for the Okta community.
