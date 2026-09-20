This guide walks you through connecting TakoAI to your Slack workspace so your team can query Okta data directly from Slack using `/tako`.

**What you'll need:**

- TakoAI already installed and running
- Slack workspace admin permissions (to create and install apps)
- About 15 minutes

---

## Upgrading an existing Slack app

Keep your existing app and tokens. To enable the new conversation experience:

1. Add the history scopes and matching message events for your channel types in **Part 2.2**, even if you use Socket Mode.
2. Enable **Interactivity & Shortcuts** in **Part 2.3**.
3. Reinstall the Slack app to your workspace after adding scopes, and invite the bot to the channels where it will be used.
4. Update Tako and restart the server. The current New Query dialog uses Slack's supported 3,000-character input limit.
5. Test a plain thread reply, **New Query**, and **Download CSV** using **Part 8**.

## Part 1 — Create your Slack App

### 1.1 Go to the Slack App Dashboard

Open the [Slack App Dashboard](https://api.slack.com/apps) and click **"Create New App"**.

Choose **"From scratch"**, give it a name (e.g. `TakoAI`), select your workspace, then click **Create App**.

---

### 1.2 Add Bot Permissions

In the left sidebar, click **OAuth & Permissions**.

Scroll down to **Bot Token Scopes** and add these scopes one by one:

| Scope | Why it's needed |
|---|---|
| `chat:write` | Post query results and status messages |
| `files:write` | Upload CSV exports and generated scripts |
| `commands` | Receive `/tako` slash commands |
| `app_mentions:read` | Respond when users `@mention` the bot |
| `users:read` | Look up user profiles for access control |
| `users:read.email` | Read user email addresses for allowlisting |
| `usergroups:read` | Check Slack group membership for allowlisting |

After adding scopes, scroll up and click **Install to Workspace** → **Allow**.

Once installed, copy the **Bot User OAuth Token** — it starts with `xoxb-`. You'll need this shortly.

---

### 1.3 Copy the Signing Secret

In the left sidebar, click **Basic Information**.

Under **App Credentials**, copy the **Signing Secret**. This is used to verify that incoming requests genuinely come from Slack.

---

## Part 2 — Configure commands, replies, and buttons

### 2.1 Create `/tako`

In the left sidebar, click **Slash Commands** → **Create New Command**.

Fill in:

| Field | Value |
|---|---|
| Command | `/tako` |
| Request URL | `https://your-takoai-server.com/slack/events` |
| Short Description | `Query Okta data with AI` |
| Usage Hint | `[query \| sync \| status \| history \| favorites \| help]` |

Replace `your-takoai-server.com` with the actual hostname or IP where TakoAI is running. If you're testing locally and your server isn't publicly accessible, see **Part 3 (Socket Mode)** before doing this step.

Click **Save**.

---

### 2.2 Enable mentions and thread replies

Open your app at [Slack App Dashboard](https://api.slack.com/apps). In the left sidebar, select **Event Subscriptions** and turn **Enable Events** on.

- **Socket Mode:** no public Request URL is needed. You must still subscribe to events.
- **HTTP mode:** set the Request URL to `https://your-takoai-server.com/slack/events`. Tako must be running and reachable to answer Slack's verification challenge.

Under **Subscribe to bot events**, add `app_mention`. For plain follow-up replies, also add the matching events below. Add their scopes under **OAuth & Permissions → Bot Token Scopes**.

| Where you use Tako | Bot token scope | Bot event |
|---|---|---|
| Public channels | `channels:history` | `message.channels` |
| Private channels | `groups:history` | `message.groups` |
| Direct messages, if used | `im:history` | `message.im` |
| Group direct messages, if used | `mpim:history` | `message.mpim` |

Select **Save Changes**, then **Reinstall to Workspace** after changing scopes. Enable the conversation types you use. For example, a private-channel reply needs **both** `groups:history` and `message.groups`; `app_mention` alone does not deliver ordinary replies. [Slack private-channel event reference](https://docs.slack.dev/reference/events/message.groups/)

Tako processes plain human replies only in an existing thread belonging to the requesting user. It ignores unrelated messages, edits, and bot messages. Subscribing to DM events does not make every standalone DM a new query; start with `/tako <question>`.

### 2.3 Enable buttons and the New Query dialog

Open **Interactivity & Shortcuts** and turn **Interactivity** on. This enables **New Query**, **Download CSV**, and the history/favorites buttons.

- **Socket Mode:** interactions use the existing WebSocket connection; no public Request URL is needed.
- **HTTP mode:** set the Request URL to `https://your-takoai-server.com/slack/interactions`.

Save the changes. No shortcut needs to be created.

---

## Part 3 — Local / Private Server Setup (Socket Mode)

If TakoAI is running on a private network (your laptop, internal server without a public URL), use **Socket Mode** instead of a public URL. Socket Mode makes the Slack bot connect outbound to Slack via WebSocket — no need to expose any port.

1. In the left sidebar, click **Socket Mode**
2. Toggle it **ON**
3. Generate an app-level token named, for example, `tako-socket`, with the **`connections:write`** scope. You can also do this under **Basic Information → App-Level Tokens**.
4. Copy the **App-Level Token** — it starts with `xapp-`

With Socket Mode enabled, Slack delivers commands, subscribed events, and interactions over the outbound connection. No public endpoint or ngrok tunnel is needed. Event subscriptions and interactivity must still be configured as described in Part 2. [Slack Socket Mode guide](https://docs.slack.dev/apis/events-api/using-socket-mode/)

---

## Part 4 — Configure TakoAI

Open your TakoAI `.env` file and add the following:

```env
# ===================================================================
# SLACK BOT CONFIGURATION
# ===================================================================

# Set to true to enable the Slack bot
ENABLE_SLACK_BOT=true

# From Part 1.2 — starts with xoxb-
SLACK_BOT_TOKEN=xoxb-your-bot-token-here

# From Part 1.3 — the signing secret
SLACK_SIGNING_SECRET=your-signing-secret-here

# From Part 3 — only needed if using Socket Mode, starts with xapp-
SLACK_APP_TOKEN=xapp-your-app-token-here

# How Slack delivers events: "socket" (default, no public URL needed) or "http" (public server)
SLACK_OPERATION_MODE=socket

# Optional: local conversation retention; defaults to 24 hours if omitted
SLACK_SESSION_RETENTION_HOURS=24

# ===================================================================
# ACCESS CONTROL (required — deny-by-default)
# ===================================================================
# The bot blocks ALL users unless you configure at least one option below.
# This is a safety measure — if you forget to set these, no one can query.

# Option A: Allow specific users by email (comma-separated)
SLACK_ALLOWED_EMAILS=admin@yourcompany.com,itmanager@yourcompany.com

# Option B: Allow Slack User Groups by name (comma-separated)
# Use the group handle exactly as it appears in Slack (e.g. @okta-admins → "okta-admins")
SLACK_ALLOWED_GROUPS=okta-admins,it-admins

# Option C: Allow ALL workspace users — see warning below before enabling
# SLACK_ALLOW_ALL_USERS=false
```

> ⚠️ **Security Warning — `SLACK_ALLOW_ALL_USERS=true`**
> With both allowlists empty, setting this to `true` grants **every user in your Slack workspace** the ability to query your **entire Okta tenant** — users, groups, apps, and policies. Only enable this if your workspace is small, internal, and fully trusted. For production environments, use `SLACK_ALLOWED_EMAILS` or `SLACK_ALLOWED_GROUPS` instead.

> **How access control works:**
> - **Default: locked down.** If `SLACK_ALLOWED_EMAILS`, `SLACK_ALLOWED_GROUPS`, and `SLACK_ALLOW_ALL_USERS` are all empty/false → the bot **rejects every command**
> - If either allowlist is set → a user is allowed if their email matches **OR** they are in any of the listed groups
> - With both allowlists empty, `SLACK_ALLOW_ALL_USERS=true` allows everyone. If an allowlist is configured, that allowlist still applies.
> - Users who are blocked see an ephemeral ":lock: You are not authorized" message — only they can see it

> **Changing access control requires a server restart.** After changing configuration, restart the server process. For Docker, recreate the container if its environment variables changed; a restart alone does not replace the container environment.

---

## Part 5 — Install Dependencies and Start the Server

### 5.1 Dependencies

**Docker:** No action needed — dependencies are bundled in the image.

**Source install or upgrade:** Activate the virtual environment used to run Tako, then install the repository's requirements:

```bash
python -m pip install -r requirements.txt
```

This installs the Slack dependencies at the versions specified by the project.

### 5.2 Start TakoAI

```bash
python main.py
```

Check the startup logs. You should see:

**Socket Mode (`SLACK_OPERATION_MODE=socket`):**

```
Slack bot routes enabled
Slack routes mounted: /slack/events, /slack/interactions
Slack Bolt app created successfully
Slack Socket Mode task started (SLACK_OPERATION_MODE=socket)
```

**HTTP Mode (`SLACK_OPERATION_MODE=http`):**

```
Slack bot routes enabled
Slack routes mounted: /slack/events, /slack/interactions
Slack Bolt app created successfully
Slack running in HTTP mode (SLACK_OPERATION_MODE=http) — ensure server has a public URL
```

If you configured group allowlisting, you'll also see something like:

```
Slack access control: allowed groups resolved: okta-admins (S0123ABCD), it-admins (S0456EFGH)
```

---

## Part 6 — Invite the Bot to a Channel

The bot must be invited to a channel before it can post there.

In any Slack channel, type:

```
/invite @TakoAI
```

Invite Tako before running queries, downloading files, or using follow-ups in a channel. A slash command may reach the server without membership, but its result delivery can still fail. Private-channel message events require the bot to be a member.

Results and uploaded CSVs are visible to people who can access that Slack conversation. The query allowlist controls who can run Tako; it does not make channel results private.

---

## Part 7 — Test It

Try these commands in Slack:

### Check status

```
/tako status
```

Only you can see the response. Shows database health, last sync time, and how many users/groups/apps are synced. If it says "no data", run a sync first.

### Sync Okta data

```
/tako sync
```

Triggers a full sync of your Okta data into the local database. Progress updates post to the channel every 10 seconds. Run this once before querying.

### Run a query

```
/tako list all active users
/tako which apps use SAML?
/tako how many groups have more than 50 members?
```

### View query history

```
/tako history
```

Shows your last 5 queries with **▶ Run** and **☆ Star** buttons. Only you can see it.

### View favorites

```
/tako favorites
```

Shows your starred queries. Use **▶ Run** to execute the saved script again. This performs retrieval again; it is different from downloading an already saved result.

### Get help

```
/tako help
```

---

## Part 8 — Results, follow-ups, and downloads

### Preview and refine results

Tako shows up to **10 rows** in the message preview, along with the retrieved result count. Larger results can be downloaded as CSV.

To refine a result, reply in **the same result thread** using plain text, for example:

```text
Just show their email addresses.
```

If Tako asks a clarification question, answer in that same thread. It retains the question and prior result context. You can also mention `@TakoAI` in the result thread.

Do not use `/tako` inside a thread: Slack does not support custom slash commands there. [Slack slash-command limitations](https://docs.slack.dev/interactivity/implementing-slash-commands/)

### Start a new question

Select **New Query**, enter a question in the dialog, and select **Ask**. Tako starts a fresh thread without the old question's context. The dialog accepts up to 3,000 characters.

You can also enter `/tako <question>` in the main channel composer, outside an existing thread. Merely replying in another unrelated thread does not start a Tako session.

### Download CSV

Select **Download CSV** to upload the saved retrieved rows into the same Slack thread. Open the uploaded file to download it. The button appears for tabular results with rows and does **not** rerun the LLM or retrieval.

The CSV contains all rows saved for that result, which may still be partial if the query was incomplete. Check the result status and requested scope before relying on it. AI can make mistakes. Please validate the data provided.

Slack uses the app's `files:write` permission for this upload; there is no Teams-style OneDrive consent step. Access is checked again for follow-ups and button actions. Another user cannot use your Download CSV button to retrieve your local result, but anyone with access to the conversation may see a file after it is uploaded.

### Quick conversation test

1. In a channel containing the bot, send `/tako list all users of all statuses`.
2. Open its result thread and reply `Just show their email addresses.` Confirm that Tako responds in the same thread.
3. Select **Download CSV** and confirm that the saved rows arrive as a Slack file.
4. Select **New Query**, submit another question, and confirm that it starts a separate thread.

## Part 9 — Session retention

```env
# Optional: defaults to 24 hours of inactivity. Valid range: 1–8760.
SLACK_SESSION_RETENTION_HOURS=24
```

Restart Tako after changing configuration. Cleanup runs at startup and hourly in both Socket and HTTP modes, with active queries and downloads protected. It removes expired local session folders, saved results, and their conversation database records. Downloads may expire; the button then asks you to start a new query.

When a container is stopped or crashes, cleanup stops too. The next startup checks the saved timestamps. Keep `CHAT_SESSIONS_DIR` and `DB_DIR` on persistent Docker volumes to retain context across container replacement.

Cleanup does not delete messages or files already uploaded to Slack, or query history/favorites. Old thread messages remain visible after their local context expires. Start a new query when that context is no longer available.

---

## Troubleshooting

| Problem | What to check |
|---|---|
| `/tako` does nothing | Server logs — ensure `ENABLE_SLACK_BOT=true` and bot token/signing secret are set |
| `dispatch_failed` error in Slack | You're using `SLACK_OPERATION_MODE=http` but Slack can't reach your server. Switch to `SLACK_OPERATION_MODE=socket` for local/private servers. |
| "Processing..." never updates | Check the server log for query or delivery errors. In Socket Mode, confirm the outbound connection is running. In HTTP mode, confirm Slack can reach the configured endpoints. |
| ":lock: You are not authorized" | Your email isn't in `SLACK_ALLOWED_EMAILS` and you're not in any group in `SLACK_ALLOWED_GROUPS`. Add your email to `SLACK_ALLOWED_EMAILS`, or add your Slack group handle to `SLACK_ALLOWED_GROUPS`. See Part 4 for allowlist behavior; restart after changing access settings. |
| Plain thread replies never reach Tako | Enable Events and subscribe to the matching message event, even in Socket Mode. For private channels, add `groups:history` plus `message.groups`, save, reinstall, and invite the bot. Reply as the original requesting user in its result thread. |
| `/tako is not supported in threads` | Use a plain reply in the result thread. Start fresh with New Query or `/tako <question>` outside the thread. |
| Buttons do nothing | Enable Interactivity & Shortcuts. In HTTP mode, verify `/slack/interactions`; in Socket Mode, check the active connection and server logs. |
| New Query fails with `views.open` / `max_length` | Update Tako and restart the server. The corrected dialog uses 3,000 characters; older code incorrectly specified 8,000. |
| CSV button says results expired or unavailable | Local results have expired or were lost during container replacement. Start a new query; check retention settings and persistent volumes. |
| Download says the thread is busy | Wait for the active query or download to finish, then retry. |
| Old thread remains but context is unavailable | Slack messages can outlive local session retention. Start a new query. |
| Everyone gets "not authorized" | Access control is deny-by-default. You must set at least one of: `SLACK_ALLOWED_EMAILS`, `SLACK_ALLOWED_GROUPS`, or `SLACK_ALLOW_ALL_USERS=true` |
| Changed `.env` but nothing happened | Restart the server process. If container environment variables changed, recreate the container with the updated configuration. |
| Group access not working | Check that the group name in `SLACK_ALLOWED_GROUPS` exactly matches the Slack group handle. Check server logs for warnings. Also ensure `usergroups:read` scope is added. |
| "No synced data" warning on queries | Run `/tako sync` first to populate the local database |
| Permission error uploading files | Ensure the `files:write` scope is added and the app has been reinstalled after adding it |
| Scopes not taking effect | After adding new scopes in the Slack dashboard, you must **reinstall** the app to the workspace for them to apply |

---
