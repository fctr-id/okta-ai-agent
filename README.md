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
    <a href="#demo">Demo</a> ·
    <a href="#why-tako">Why Tako</a> ·
    <a href="#ai-provider-support">AI providers</a> ·
    <a href="#upgrading">Upgrading</a> ·
    <a href="#documentation--support">Docs &amp; support</a>
  </p>

  <p>
    <a href="VERSION.md">
      <img src="./media/badges/preview.svg" alt="v3.2.0-beta" width="170" height="22">
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

**The first AI agent built for Okta.** Ask about users, groups, applications, policies, devices, and access in plain English. Tako finds the data, checks its queries, and returns results you can explore, follow up on, and export as CSV or reusable Python scripts.

Self-hosted, works with your choice of AI provider, and available in the browser, Slack, Teams, and the command line.

> [!NOTE]
> Upgrading from an earlier version? Read [Upgrading](#upgrading) before you restart Tako.

## Demo

https://github.com/user-attachments/assets/7a27ebc4-39a0-400f-bf16-505afca7ca3d

*Query discovery, execution progress, and CSV export. Recorded on an earlier version of the interface.*

### Try questions like

- "List active users in Engineering with no MFA enrolled."
- "Show the roles for those users." — a follow-up using the previous results
- "Find the SAML certificate expiry date for all active SAML applications."

## Why Tako?

General-purpose AI assistants can call Okta APIs, but they spend time and tokens working out which endpoints to use, how to paginate, and how resources relate. Tako is built for Okta, so it reaches accurate answers with **fewer tokens, less time, and lower cost**.

| What Tako does | How it helps |
|---|---|
| Okta-specific knowledge | Guides the model to the Okta data your question needs. |
| Picks the right source | Uses synced data, live Okta data, or specialized analysis to suit the question. |
| Handles large results | Works with large result sets without sending every record to the model. |
| Checks its queries | Tests generated queries before using them in your answer. |
| Builds on earlier answers | Follow-ups use previous results instead of starting over. |
| Reuses successful queries (optional) | Reruns or adapts saved scripts to skip repeated discovery. |

Results and savings vary by model, question, tenant size, and data freshness.

### Where your data comes from

- **Live API** — Query Okta directly, with no sync needed.
- **Local database** — Sync users, groups, applications, policies, devices, authenticators, and their assignments to local SQLite for fast SQL queries.
- **Both** — Combine synced and live data when a question needs it.

Tako chooses the source for each question. To use live data, say so in your question, for example "Using the live Okta API, …". The first sync of a large tenant can take a while.

## Features

- **107 Okta endpoints** — Detailed guidance for users, groups, apps, policies, devices, and authenticators.
- **Faster repeat queries** — Optionally reuse or adapt saved scripts to save time and tokens.
- **Follow-up conversations** — Refine earlier answers, reopen saved sessions, and keep favorites.
- **AI Summary and progress** — A short explanation of each answer, with step-by-step activity.
- **Interactive tables and exports** — Choose columns, sort, group, and export complete CSVs or Python scripts.
- **Slack and Teams** — Ask questions, follow up, and download CSVs from chat.
- **CLI automation** — Run queries and syncs from scripts or scheduled jobs.
- **Self-hosted** — Docker on AMD64 or ARM64 with your preferred cloud or local AI provider.

See [VERSION.md](VERSION.md) for the full release history.

## Quick Start (Docker)

For a local installation without Docker, see the [installation guide](https://github.com/fctr-id/okta-ai-agent/wiki/Installation).

### Prerequisites

- Docker with Docker Compose. Images support AMD64 (Intel/AMD) and ARM64 (Apple Silicon, AWS Graviton).
- An Okta Identity Engine tenant with [OAuth 2.0 or API token authentication configured](https://github.com/fctr-id/okta-ai-agent/wiki/Authentication-&-Authorization-%E2%80%90-Oauth-2-and-API-tokens).
- Access to a [supported AI provider](#ai-provider-support).

### 1. Download the files

<details>
<summary>Linux / macOS</summary>

```bash
mkdir okta-ai-agent
cd okta-ai-agent
mkdir -p sqlite_db chat_sessions logs certs

curl -O https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/.env.sample
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
New-Item -ItemType Directory -Path okta-ai-agent
Set-Location okta-ai-agent
New-Item -ItemType Directory -Path sqlite_db, chat_sessions, logs, certs -Force

Invoke-WebRequest -Uri "https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/docker-compose.yml" -OutFile "docker-compose.yml"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/fctr-id/okta-ai-agent/main/.env.sample" -OutFile ".env"
```

</details>

### 2. Configure `.env`

Fill in your Okta details and one AI provider. Everything else in the file is optional.

```dotenv
# Okta (TOKEN_METHOD can be API_TOKEN or OAUTH2)
OKTA_CLIENT_ORGURL=https://your-domain.okta.com
TOKEN_METHOD=API_TOKEN
OKTA_API_TOKEN=your-api-token
OKTA_CONCURRENT_LIMIT=18

# AI provider: openai, google, anthropic, vertex_ai, azure_openai, bedrock, or openai_compatible
AI_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_REASONING_MODEL=gpt-5.6-terra
OPENAI_CODING_MODEL=gpt-5.6-terra
```

For OAuth 2.0, other providers, and optional features, follow the comments in `.env`.

**Stay signed in across restarts:** set `JWT_SECRET_KEY` in `.env`. Without it, Tako generates a new key at each start and everyone must sign in again. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

**Reasoning:** the sample sets `AI_REASONING_EFFORT=high`. If your model doesn't support it, set it to `none`. See [Reasoning setting](#reasoning-setting).

**Rate limits:** `OKTA_CONCURRENT_LIMIT=18` is a safe starting point for lower-rate-limit tenants. Lower it if other integrations share your Okta limits or if syncs hit rate limits; your Okta rate-limit dashboard shows current usage. See Okta's [rate-limit](https://developer.okta.com/docs/reference/rate-limits/) and [concurrency](https://developer.okta.com/docs/reference/rl2-concurrency/) documentation.

### 3. Start Tako

```bash
docker compose up -d
docker compose logs -f
```

Open [https://localhost:8001](https://localhost:8001). Tako uses a self-signed certificate by default, so your browser will show a security warning. To use your own certificate, place `cert.pem` and `key.pem` in the `certs` folder.

> [!NOTE]
> By default, Tako is only reachable from the machine it runs on. To open it from other machines, change `127.0.0.1:8001:8001` to `8001:8001` in `docker-compose.yml` and add your URL to `ALLOWED_ORIGINS`. Only do this on a trusted network or behind a reverse proxy.

### 4. Create your admin account

On first start, Tako prints a one-time setup token in the logs:

```bash
# Linux / macOS
docker compose logs | grep "Setup token"

# Windows (PowerShell)
docker compose logs | Select-String "Setup token"
```

Enter the token on the setup screen to create the first admin account. A new token is generated if Tako restarts before setup is complete.

### 5. Ask your first question

1. **Using synced data:** open the sync menu at the top right, select **Sync now**, and wait for it to finish. Then ask: "List active users in Engineering."
2. **Without a sync:** ask "Using the live Okta API, list five active users."
3. Ask a follow-up in the same conversation, or export the results.

AI can make mistakes. Validate results before acting on them.

## AI Provider Support

Tako supports OpenAI, Google AI Studio, Google Vertex AI, Anthropic, Azure OpenAI, AWS Bedrock, and OpenAI-compatible endpoints, including local models through Ollama.

Set `AI_PROVIDER` and fill in that provider's section in `.env`. You can use the same model for reasoning and coding, or a different model for each. Model choice affects answer quality, speed, and cost.

### Tested models

| Provider | Tested model |
|---|---|
| DeepSeek | DeepSeek V4.1 Flash |
| Z.ai | GLM 5.3 |
| Google | Gemini 3.8 Flash |
| OpenAI | GPT-5.6 Terra |
| Anthropic | Claude Haiku 4.5 |

DeepSeek and Z.ai models connect through `openai_compatible`. Start with a tested model; if you choose another, try it with your usual Okta questions first. Smaller, older, or untested models may give less reliable answers.

### Reasoning setting

The sample sets `AI_REASONING_EFFORT=high`, which can make answers slower and more expensive. If your model doesn't support it, set `AI_REASONING_EFFORT=none` or remove the line, then restart Tako. Some models still reason by default.

## CLI Tools for Automation

Run queries and syncs from scripts or scheduled jobs after setup.

```bash
# Run a query
python scripts/tako-cli.py "list all users created in last 30 days"

# Generate a reusable script only
python scripts/tako-cli.py "show suspended users" --scriptonly

# Export results as CSV
python scripts/tako-cli.py "find users with MFA enabled" --csv

# Sync Okta to the local database
python scripts/sync_okta_to_db.py
```

With Docker, prefix each command with `docker exec okta-ai-agent`, for example `docker exec okta-ai-agent python scripts/sync_okta_to_db.py`.

## Slack Bot Integration

Allowlisted users can query Okta from Slack, follow up in result threads, and download CSVs.

The bot is disabled by default. Set `ENABLE_SLACK_BOT=true` in `.env` and follow the [Slack setup guide](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Slack-Bot-Setup-&-Testing-Guide).

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

- **Allowlist access** — `SLACK_ALLOWED_EMAILS` or `SLACK_ALLOWED_GROUPS` control who can use the bot.
- **Socket Mode** — Outbound connection to Slack; no public URL or port forwarding needed.
- **Per-action checks** — Access is verified for every command and button.

## Microsoft Teams Bot Integration

Query Okta in a personal Teams chat, ask follow-ups, and download results as CSV. Access is limited to members of allowed Microsoft Entra groups.

The bot is disabled by default. Follow the [Teams setup guide](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Teams-Bot-Setup) to configure access and deploy the Teams app package.

### Build the Teams app package

From a clone of this repository, run the builder and enter your Entra **Application (client) ID** when prompted:

```bash
python scripts/build_teams_package.py
```

The script prints the path of the ZIP, saved under `src/integrations/teams/app_package/output/`. Upload it to Teams as described in the setup guide.

### Security Highlights

- **Tenant restriction** — Requests must match your `TEAMS_TENANT_ID`.
- **Group allowlist** — `TEAMS_ALLOWED_GROUP_IDS` lists allowed Entra group IDs; users must belong to at least one.
- **Verified membership** — Access is denied if membership can't be confirmed. The bot won't start with an empty allowlist.

## Security & Privacy

### Authentication and authorization

- OAuth 2.0 or API tokens — Queries use the permissions granted to your configured Okta credentials. Configure least-privilege read access for the data you need.
- Initial admin setup — A one-time setup token gates creation of the first application admin account.
- Web sessions — Signed using a configured private key or an automatically generated key. See [Upgrading](#upgrading) for restart behavior and shared-key configuration.
- Optional Slack and Teams access — Explicit allowlists control who can use each bot.

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

<a id="important-notes-for-v32"></a>

## Upgrading

Pull the latest image and restart. Synced data, conversations, and accounts are kept in the mounted folders.

```bash
docker compose pull
docker compose up -d
```

Also download the latest `docker-compose.yml`, and compare your `.env` with the latest [`.env.sample`](.env.sample) for new settings.

### Notes for v3.2

Review these before upgrading from an earlier version. Restart Tako after changing settings. If your model doesn't support the default reasoning setting, see [Reasoning setting](#reasoning-setting).

<details>
<summary><strong>Login sessions</strong></summary>

Without a configured `JWT_SECRET_KEY`, Tako generates a new key at startup. Restarts require a fresh login; accounts, saved conversations, and synced data stay intact.

- Multiple workers or containers must share the same configured key.
- Changing the key signs users out. Old default placeholders are replaced automatically; custom keys shorter than 32 bytes must be replaced or cleared.
- See [`.env.sample`](.env.sample) for the key-generation command.

</details>

<details>
<summary><strong>Azure OpenAI</strong></summary>

Use an `AZURE_OPENAI_ENDPOINT` ending in `/openai/v1/`, without `/responses`. Both Azure model settings take deployment names. `AZURE_OPENAI_VERSION` is no longer needed.

</details>

<details>
<summary><strong>Slack &amp; Teams</strong></summary>

- Existing Slack apps need [updated permissions and event settings](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Slack-Bot-Setup-%26-Testing-Guide#upgrading-an-existing-slack-app) for follow-ups and result buttons.
- Teams is optional; enable it with the [Teams setup guide](https://github.com/fctr-id/okta-ai-agent/wiki/Tako-AI-%E2%80%90-Teams-Bot-Setup).
- Bot context and local exports expire after 24 hours of inactivity by default; change this with `SLACK_SESSION_RETENTION_HOURS` and `TEAMS_SESSION_RETENTION_HOURS`. Messages and files already delivered are unaffected.

</details>

<details>
<summary><strong>Saved-query reuse (optional)</strong></summary>

Set `QUERY_PROCEDURES_ENABLED=true` to enable the query library. Saved scripts are validated before reuse and run again against your configured data sources. Generic queries can be reused by other users in the same tenant. If reuse fails, Tako falls back to normal discovery.

</details>

See [VERSION.md](VERSION.md) for full release notes.

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

🌟 © 2025–2026 Fctr. All rights reserved. Meet Tako, made with ❤️ for the Okta community.
