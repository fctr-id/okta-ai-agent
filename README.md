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
    <a href="#important-notes-for-v32">v3.2 upgrade notes</a> ·
    <a href="#why-tako">Why Tako</a> ·
    <a href="#demo">Demo</a> ·
    <a href="#ai-provider-support">AI providers</a> ·
    <a href="#documentation--support">Docs &amp; support</a>
  </p>

  <p>
    <a href="VERSION.md">
      <img src="./media/badges/preview.svg" alt="v3.1.0-beta — Unreleased" width="170" height="22">
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
| Okta-specific knowledge | Gives the model guidance on where to find the Okta data needed to answer your question. |
| Targeted data access | Chooses saved data, live Okta data, or specialized analysis to suit the question. |
| Efficient data handling | Works with large results without repeatedly sending every record to the model. |
| Checked queries | Checks generated queries before using them to prepare your answer. |
| Result reuse | Builds follow-ups on earlier results instead of starting over. |

Results and savings vary by model, question, tenant size, and data freshness.

### Data access

- API mode — Query live Okta data without an initial database sync.
- Database mode — Sync supported entities to local SQLite for SQL queries.
- Hybrid mode — Combine synced data with live API results when needed.

Synced data includes users, groups, applications, policies, devices, enrolled authenticators, and their assignments. Large tenants may take longer to complete the first sync.

<a id="important-notes-for-v32"></a>

## ⚠️ Important notes for v3.2

Review these settings before upgrading. Expand a topic for details; restart Tako after changes.

<details>
<summary><strong>Login sessions</strong></summary>

Without a configured `JWT_SECRET_KEY`, Tako generates a new key at startup. Restarts require a fresh login; accounts, saved conversations, and synced data stay intact.

- Multiple workers or containers must share the same configured key.
- Changing the key signs users out. Old default placeholders are replaced automatically; custom keys shorter than 32 bytes must be replaced or cleared.
- See [`.env.sample`](.env.sample) for the key-generation command.

</details>

<details>
<summary><strong>AI reasoning</strong></summary>

`AI_REASONING_EFFORT=high` can increase time and cost, and not all models support it. Set it to `none` or remove it to use model defaults. Some models still think automatically.

See [tested models and thinking settings](#ai-provider-support).

</details>

<details>
<summary><strong>Azure OpenAI</strong></summary>

Use an `AZURE_OPENAI_ENDPOINT` ending in `/openai/v1/`, without `/responses`. Both Azure model settings take deployment names. `AZURE_OPENAI_VERSION` is no longer needed. See [`.env.sample`](.env.sample).

</details>

<details>
<summary><strong>Slack &amp; Teams</strong></summary>

- Existing Slack apps need [updated permissions and event settings](wiki/Slack-Bot-Setup.md#upgrading-an-existing-slack-app) for follow-ups and result buttons.
- Teams is optional; enable it with the [Teams setup guide](wiki/Teams-Bot-Setup.md).
- Bot context and local exports expire after 24 hours of inactivity by default. The guides explain retention settings; messages and files already delivered remain unaffected.

</details>

[Full release notes](VERSION.md)

## Demo

https://github.com/user-attachments/assets/7a27ebc4-39a0-400f-bf16-505afca7ca3d

*Query discovery, execution progress, and CSV export. This recording shows an earlier interface; the redesigned UI is complete.*

### Try questions like

- "List active users in Engineering with no MFA enrolled."
- "Show the roles for those users." — a follow-up using the previous result set
- "Find the SAML certificate expiry date for all active SAML applications."

## Features

- Conversation and follow-ups — Build on saved results within a session.
- Visible progress — Inspect discovery, execution, tables, and generated scripts.
- History and favorites — Revisit recent queries and save frequent ones.
- CSV and Python export — Export results for reports or download reusable Python scripts.
- CLI automation — Run queries and database syncs from scheduled jobs.
- Optional Slack bot — Query your tenant with `/tako`; disabled by default.
- Docker deployment — Self-host on AMD64 or ARM64 with your chosen AI provider.

## AI Provider Support

Tako supports OpenAI, Google AI Studio, Google Vertex AI, Anthropic, Azure OpenAI, AWS Bedrock, and OpenAI-compatible endpoints, including local deployments such as Ollama.

Choose a provider and fill in its section in `.env`. You can use the same model for reasoning and coding, or choose a different model for each. Model choice affects answer quality, response time, and cost.

### Tested models

The Fctr Identity team has tested the following models with Tako for the upcoming v3.1.0-beta release:

| Provider | Tested model |
|---|---|
| DeepSeek | DeepSeek V4.1 Flash |
| Z.ai | GLM 5.3 |
| Google | Gemini 3.8 Flash |
| OpenAI | GPT-5.6 Terra |
| Anthropic | Claude Haiku 4.5 |

Start with one of the tested models above. You can also choose a more capable model, but try it with your usual Okta questions first. Smaller, older, or untested models may give less reliable answers or fail to complete some requests.

### Reasoning and thinking settings

The sample sets `AI_REASONING_EFFORT=high` to give supported models more time to think. This can make responses slower and more expensive.

If your model does not support this setting, use:

```dotenv
AI_REASONING_EFFORT=none
```

You can also remove the variable. Restart Tako after making the change. This uses your model's default behavior; some models still think automatically.

## Quick Start (Docker)

For a local installation without Docker, see the [installation guide](https://github.com/fctr-id/okta-ai-agent/wiki/Installation).

### Prerequisites

- Docker with Docker Compose.
- An Okta Identity Engine tenant with [OAuth 2.0 or API token authentication configured](https://github.com/fctr-id/okta-ai-agent/wiki/Authentication-&-Authorization-%E2%80%90-Oauth-2-and-API-tokens).
- Access to a [supported AI provider](#ai-provider-support).

> [!IMPORTANT]
> Review the [important notes for v3.2](#important-notes-for-v32), especially login signing keys and your model's reasoning setting, before starting Tako.

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

### Ask your first question

After creating your admin account and signing in:

1. For saved-data queries, open the sync menu at the top right, select **Sync now**, and wait for it to finish. You can then ask: "List active users in Engineering."
2. To start without a sync, ask for live data explicitly: "Using the live Okta API, list five active users."
3. Review the answer, then ask a follow-up in the same conversation or export the results.

AI can make mistakes. Validate results before acting on them.

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

## Microsoft Teams Bot Integration

Query your Okta tenant in a personal Teams chat, ask follow-up questions, and download results as CSV. Access is restricted to members of your allowed Microsoft Entra groups.

The bot is disabled by default. Follow the [Teams installation and setup guide](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Teams-Bot-Setup) to install the integration, configure access, and deploy the Teams app package.

## Security & Privacy

### Authentication and authorization

- OAuth 2.0 or API tokens — Queries use the permissions granted to your configured Okta credentials. Configure least-privilege read access for the data you need.
- Initial admin setup — A one-time setup token gates creation of the first application admin account.
- Web sessions — Signed using a configured private key or an automatically generated key. See [v3.2 upgrade notes](#important-notes-for-v32) for restart behavior and shared-key configuration.
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

## Documentation & Support

### Documentation

| Guide | What it covers |
|---|---|
| [Installation](https://github.com/fctr-id/okta-ai-agent/wiki/Installation) | Local setup and alternatives to Docker. |
| [Authentication](https://github.com/fctr-id/okta-ai-agent/wiki/Authentication-&-Authorization-%E2%80%90-Oauth-2-and-API-tokens) | OAuth 2.0, API tokens, and Okta permissions. |
| [Slack bot](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Slack-Bot-Setup-&-Testing-Guide) | Bot configuration, access, and testing. |
| [Teams bot](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Teams-Bot-Setup) | Installation, Entra group access, and Teams app setup. |
| [Supported endpoints](https://github.com/fctr-id/okta-ai-agent/wiki/Tako:-Supported-Okta-API-Endpoints) | Okta API coverage. |
| [Version history](VERSION.md) | Releases, migrations, and security fixes. |

### Get Help

Before opening an issue, check your configuration, Okta permissions, AI provider setup, and application logs. Include reproduction steps and redacted errors; keep credentials and tenant data out of issue reports.

- 🐛 [GitHub Issues](https://github.com/fctr-id/okta-ai-agent/issues) - Bug reports and feature requests
- 📧 Email: support@fctr.io - General support  
- 💬 Slack: dan@fctr.io - Quick support

## Contributing

Interested in contributing? We'd love your help! Reach out to dan@fctr.io

## Contributors

<a href="https://github.com/fctr-id/okta-ai-agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=fctr-id/okta-ai-agent" alt="Tako contributors" />
</a>

## License

See [LICENSE](LICENSE) for details.

---

🌟 © 2025 Fctr. All rights reserved. Meet Tako, made with ❤️ for the Okta community.
