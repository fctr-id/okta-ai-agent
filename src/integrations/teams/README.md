# Microsoft Teams bot (initial implementation)

Tako can answer Okta questions and follow-ups in a Teams **personal chat**. It uses
the existing orchestrator, model settings, database and script security validation.
It does not introduce another model configuration or entity-specific prompts.

Implemented: SDK-authenticated messages, tenant/group authorization, durable
deduplication, two query workers, help/status/cancel commands, result previews,
clarification responses, and cancellation/timeout cleanup. This integration is
opt-in and has not yet been validated against a live customer Teams tenant.

## Install and configure

1. Install the normal application dependencies, then
   `python -m pip install -r requirements-teams.txt`. The integration uses Microsoft
   Teams SDK for Python 2.1.0. For Docker, build with
   `docker build --build-arg INSTALL_TEAMS_BOT=true -t tako-teams .`.
2. Create a **single-tenant Entra app registration** and matching Azure Bot. Use the app/client GUID, not the Enterprise
   application's object ID. Set the messaging endpoint to
   `https://your-public-tako-host/teams/messages` behind a trusted HTTPS proxy.
   Microsoft's service must reach this endpoint; localhost and self-signed public
   certificates do not work. Keep the normal web UI authentication enabled.

   **Enable the Teams channel before uploading the app package:** open the Azure
   Bot resource's **Settings → Channels**. Under **Available Channels**, select
   **Microsoft Teams**, complete the commercial Teams configuration, accept any
   required terms, and save. Refresh the Channels page and confirm that
   **Microsoft Teams** appears in the connected channels list with health status
   **Healthy**. If it is already listed as Healthy, this step is complete.

   Saving the messaging endpoint does not enable this channel. Without it, Teams
   can reject the package with **Invalid Bot — Please make sure the bot is
   registered and Teams channel is enabled**. Direct Line and Web Chat do not
   substitute for the Microsoft Teams channel. A Healthy channel confirms the
   channel setup; test a message afterward to verify the Tako connection.
3. Grant the app Microsoft Graph **application** permissions `User.ReadBasic.All`
   and `GroupMember.Read.All`, with administrator consent. Configure permitted
   Entra security groups. Membership is transitive, and any matching group grants
   access. Hidden-membership groups need additional permissions; avoid them for
   the initial setup.
4. Set these environment variables server-side (also listed in `.env.sample`):

   ```text
   TEAMS_ENABLE=true
   TEAMS_TENANT_ID=<tenant GUID>
   TEAMS_CLIENT_ID=<app/client GUID>
   TEAMS_CLIENT_SECRET=<private application secret>
   TEAMS_ALLOWED_GROUP_IDS=<group GUID>,<another group GUID>
   ```

   Missing or invalid enabled configuration fails startup. With the enable flag
   false, the SDK is not imported and no bot endpoint is mounted. Secrets are not
   included in the Teams ZIP or sent to end users.
5. Run **one API process/worker and one replica**, with persistent `DB_DIR` and
   `CHAT_SESSIONS_DIR`. A process lock prevents two workers sharing the Teams inbox.
   Separate database directories do not provide multi-replica coordination.
6. Generate the installation package using the bundled `teams-app` folder:

   ```powershell
   python teams-app/build.py
   ```

   Enter your Entra Application (client) ID when prompted. The folder contains the
   icons and manifest template; no extra Python packages are needed. The script
   creates `teams-app/output/Tako-AI-Teams-<client-id>.zip` and prints the full path
   to upload. Defaults link to the project's repository, privacy information, and
   license; use `--website`, `--privacy`, and `--terms` for deployment-specific URLs.

   The default Teams app ID is deterministic for the bot client ID; use `--app-id`
   when updating an existing Teams application. Validate the ZIP in Teams Developer
   Portal, then distribute through the organization's Teams admin process.
   Installation is not authorization: the backend independently checks access.

## Behavior and limits

- Messages continue the user's current personal-chat session, including clarification answers.
  **New Query** (or `new`) resets context for the next message. Previous result cards stay visible.
  Session IDs are stored in the durable inbox database and survive restarts.
- Only authenticated Bot Service activities from the configured tenant's personal chats are accepted.
  Direct Entra/Agent ID callers, channel/group chats, incoming files, and unrelated card actions remain unsupported.
- Graph membership is checked before execution and again before delivering results.
  Authorization failures never start Okta or LLM work. Membership is not cached.
- One query per user, two simultaneous queries per instance, at most 16 pending or
  active queries. A separate command worker handles `help`, `status`, and `cancel`.
  Query messages are limited to 8,000 characters. Overloaded requests return 429.
- The whole request has a 15-minute deadline from arrival, with a 120-second script
  limit. `cancel` stops the sender's pending/running query; completed API effects
  cannot be rolled back. Generated script subprocesses are killed and reaped on
  cancellation and timeout.
- A temporary working card is removed after a new final answer is delivered.
  Table previews show the first ten
  rows and four columns using the native Adaptive Card Table element, with an
  aligned-column fallback for older clients. Header labels and data keys are
  normalized separately; long values are visibly truncated. Native typing dots
  refresh while a query runs and stop on completion, error, or cancellation.
  Typing failures are best-effort and never fail the query. Partial answers and
  clarifications are distinct from successful empty results. Errors do not include
  raw stack traces or generated scripts.
- **Download CSV** exports the saved retrieved rows without rerunning the question. Teams first asks
  permission to save the file to the user's OneDrive, then shows a native file card. Consent is
  single-use, expires after one hour, and is bound to the requesting tenant, user, conversation,
  and result. Only Microsoft-hosted OneDrive/SharePoint upload URLs are accepted; uploads use
  bounded sequential chunks with no redirects or bot/Graph authorization headers. No extra Graph
  file permissions are required. The app package must have `supportsFiles=true` (version 0.2.0).
- Identical activity redeliveries are deduplicated for 24 hours. Queued, unexpired
  jobs survive restarts; in-flight jobs become interrupted and are not replayed.
  The inbox stores queries and trusted routing identifiers under `DB_DIR`, not
  bearer tokens. File-consent upload URLs are temporarily held only in queued/running upload jobs and cleared at completion, expiry, or interruption. Terminal inbox rows are purged after 24 hours. Teams runtime
  folders under `CHAT_SESSIONS_DIR` are swept at startup and hourly, including
  while the bot is idle. `TEAMS_SESSION_RETENTION_HOURS` defaults to 24 (valid
  range: 1–8760); any recent file activity extends retention. Queued/running jobs
  are protected. Expiry removes the entire Teams session folder and its artifacts,
  results, exports, and associated conversation database rows. Web sessions and linked directories are
  not deleted by this cleanup. Already-delivered Teams messages/files remain in Teams.
- Failed/uncertain message delivery never reruns the query. Only explicit 429
  sends are retried. Restart interruptions require the user to resend the question;
  there is no automatic recovery notification yet.
- Treat already-sent Teams content as disclosed to the recipient; membership
  revocation cannot recall previously delivered data.

## Verification

Incoming decisions are logged to the console and `logs/okta_ai_agent.log`.
Rejections include a fixed reason, text length, attachment counts, and whether a
card-action value was present; accepted requests include the queued job ID.
These diagnostics exclude message text, attachment contents, URLs, and tokens.
Worker failures include the processing stage, code locations, missing filename,
and HTTP status when available. Runtime folders stay under the configured
`CHAT_SESSIONS_DIR`; a compact tenant/user hash avoids unnecessarily long Windows
paths. Cards are sent without a separate text message so Teams preserves the
activity ID used to update progress with the final result or error.
Before saving a request, Tako normalizes pasted line endings and nonbreaking
spaces, trims outer whitespace, and removes control characters and invisible
direction overrides. It preserves punctuation, query operators, Unicode text,
and emoji joiners. Empty cleaned messages and raw text over 8,000 characters are
rejected. This input cleanup does not replace authorization, generated-code
validation, or output escaping, and does not claim to prevent prompt injection.
Teams' `text/html` companion attachments are ignored when message text is present;
file attachments and card actions remain unsupported. See Microsoft's
[message activity example](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/build-conversational-capability#receive-a-message-activity).

Run `python -m unittest discover -s tests -p "test_teams*.py"` after installing the
optional dependency. Tests use synthetic identities, mock Graph, and local signing
keys; they do not contact Microsoft or Okta or spend LLM tokens.

Before release, validate an actual package installation, connector JWT/proactive
send roundtrip, nested group access and revocation, desktop/mobile card rendering,
and a real query/cancel/restart flow. Linux Docker execution also needs a smoke
test. Conversation and file-consent tests use temporary SQLite databases and mocked
Microsoft endpoints; the latest follow-up and CSV flows still require live validation.

References: [Teams Python SDK](https://github.com/microsoft/teams.py/tree/v2.1.0),
[SDK HTTP integration](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/in-depth-guides/server/http-server),
[Graph membership permissions](https://learn.microsoft.com/en-us/graph/api/directoryobject-checkmembergroups?view=graph-rest-1.0),
[Azure configuration](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/teams/azure-configuration).
