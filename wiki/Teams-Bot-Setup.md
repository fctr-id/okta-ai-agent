# Set up Tako AI in Microsoft Teams

Connect your own Tako instance to a bot in your Microsoft 365 tenant. Users can ask Okta questions in a personal chat; access is limited to the Entra groups you choose.

This guide covers installation, continued conversations, New Query, CSV downloads, and session cleanup. Tako currently supports personal chats in the commercial Microsoft 365 cloud; group chats, channels, and meetings are not supported.

## Upgrading an existing installation

1. Update Tako and install the optional Teams dependencies in your server environment, or rebuild your Docker image with Teams enabled (Part 4).
2. Rebuild the Teams ZIP using the same Entra client ID and upload the new package (Part 5). Package version **0.2.0** enables the file support needed for CSV downloads. Keep the same Teams app ID when updating an existing installation.
3. Restart Tako. For Docker, recreate the container when its image or environment variables change; preserve your database and session volumes.
4. Open Tako's personal chat and run the checks in Part 6. Previously posted cards do not gain new buttons automatically.

## Before you start

You need a working Tako instance, an Azure subscription, and permission to create an Entra app registration and Azure Bot resource. An administrator must approve the Graph permissions and allow installation of your custom Teams app.

Tako needs a public HTTPS address that Microsoft can reach, such as `https://tako.example.com`. Use a trusted TLS certificate and forward requests to the Tako server through your proxy. For local testing, you can use an HTTPS development tunnel. Keep the web app's existing login protection enabled.

## Part 1 — Register the application in Entra ID

1. Open the [Microsoft Entra admin center](https://entra.microsoft.com/) and select the directory where your Teams users belong.
2. Go to **Identity → Applications → App registrations → New registration**.
3. Name it **Tako AI Teams**.
4. Select **Accounts in this organizational directory only (Single tenant)**.
5. Leave **Redirect URI** blank and select **Register**. This integration uses application credentials; it does not require an interactive sign-in redirect or Teams SSO configuration.
6. On **Overview**, record these two values:

| Entra field | Tako setting |
| --- | --- |
| Application (client) ID | `TEAMS_CLIENT_ID` |
| Directory (tenant) ID | `TEAMS_TENANT_ID` |

Use the **Application (client) ID**, not the app's Object ID or the Enterprise application's Object ID. See Microsoft's [app registration guide](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app).

### Create the client secret

In the app registration, open **Certificates & secrets → Client secrets → New client secret**. Enter a description, select an expiration appropriate for your organization, and select **Add**.

Copy the secret's **Value** immediately into your server's secret configuration as `TEAMS_CLIENT_SECRET`. The **Secret ID** is not the password. The value is only shown when created; record the expiration so you can rotate it before it expires. Never put it in the Teams app package or repository. This version of Tako uses client-secret authentication. [Microsoft credential instructions](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-credentials)

## Part 2 — Grant permissions and choose who can use the bot

In the same app registration:

1. Open **API permissions → Add a permission → Microsoft Graph → Application permissions**.
2. Add **User.ReadBasic.All** and **GroupMember.Read.All**.
3. Select **Grant admin consent for your organization**, or have an authorized administrator do so. Confirm that both permissions show consent granted.

Choose **Application**, not Delegated permissions. Tako uses these permissions to check the sender's group membership without asking the user to sign in separately. Microsoft documents this combination for checking [another user's group memberships](https://learn.microsoft.com/en-us/graph/api/directoryobject-checkmembergroups?view=graph-rest-1.0).

Next, open **Entra ID → Groups → All groups**. Create or select a security group such as **Tako Teams Users**, add your test user, and copy the group's **Object ID** into `TEAMS_ALLOWED_GROUP_IDS`.

You can list multiple group GUIDs separated by commas. Membership in **any** listed group grants access, including nested membership. Start with a normal security group; hidden-membership groups require additional Graph access. Installing the Teams app alone does not grant access.

## Part 3 — Create and configure the Azure Bot

Open the [Azure portal](https://portal.azure.com/) in the same directory:

1. Select **Create a resource**, search for **Azure Bot**, and select **Create**.
2. Complete the **Basics** tab using the table below.
3. Add **Tags** if required by your organization, then select **Review + create**. Check the values and select **Create**.

| Portal field | What to enter or select |
| --- | --- |
| **Bot handle** | A name for the Azure Bot resource, such as `tako-teams-bot`. Use a name the portal accepts. |
| **Subscription** | The Azure subscription that will own the bot resource and its billing. |
| **Resource group** | Select an existing resource group or use **Create new**, for example `tako-bot-rg`. |
| **Data residency** | Choose **Global** or **Regional** according to your organization's requirements. |
| **Region** | If you selected **Regional**, choose an available region approved for your deployment. Do not copy another deployment's region automatically. |
| **Pricing tier** | Review the selected tier. Use **Change plan** if your deployment requires a different tier. |
| **Type of App** | **Single Tenant**. This matches the Entra registration created above. |
| **Creation type** | **Use existing app registration**. |
| **App ID** | The Entra **Application (client) ID** used for `TEAMS_CLIENT_ID`. |
| **App tenant ID** | The Entra **Directory (tenant) ID** used for `TEAMS_TENANT_ID`. |

The bot resource's residency selection does not relocate your Tako server or configure your AI provider's data location. Those are separate deployment settings.

Open the new Azure Bot's **Settings → Configuration**. Set **Messaging endpoint** to:

```text
https://tako.example.com/teams/messages
```

Replace the hostname with your public Tako address and save. The path is **`/teams/messages`**, not the `/api/messages` path used in some Microsoft examples.

On this **Configuration** screen, use these settings:

| Field | Setting for Tako |
| --- | --- |
| **Messaging endpoint** | Your public HTTPS address followed by `/teams/messages`. For a development tunnel, use its HTTPS hostname and ensure it forwards to the running Tako server. |
| **Enable Streaming Endpoint** | Leave unchecked. This integration receives HTTP activities and sends or updates reply cards; it does not use the Bot Service streaming endpoint. |
| **Bot Type** | Confirm **Single Tenant**. |
| **Microsoft App ID** | Confirm it matches `TEAMS_CLIENT_ID` and the Entra Application (client) ID. |
| **App Tenant ID** | Confirm it matches `TEAMS_TENANT_ID` and the Entra Directory (tenant) ID. |
| **Application Insights Instrumentation key / API key / Application ID** | Leave blank for this setup. Tako does not require an Application Insights integration. |

Select **Save** after changing the endpoint or tenant ID. If your development tunnel's hostname changes, update and save the messaging endpoint here. The **Manage Password** link relates to the app registration's credentials; keep the current secret value in Tako's `TEAMS_CLIENT_SECRET` setting.

### Enable the Microsoft Teams channel

Complete this step **before uploading the app package to Teams**:

1. In the Azure Bot resource, open **Settings → Channels**.
2. Under **Available Channels**, select **Microsoft Teams**.
3. Complete the configuration for the commercial Microsoft Teams cloud, accept any required terms, and save.
4. Return to the Channels page and select **Refresh**. Confirm **Microsoft Teams** appears in the connected channels list with health status **Healthy**. If it is already listed as Healthy, it is enabled.

Setting the messaging endpoint alone does **not** enable Teams. Direct Line and Web Chat are separate channels and do not replace this step. A Healthy channel does not confirm that your Tako server is reachable; verify that by sending a message after installation.

The Azure Bot connects Teams to your running Tako server; creating it does not deploy the Tako application. Microsoft's [Azure Bot setup instructions](https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/teams/azure-configuration) cover the portal flow.

### Local testing with ngrok

Start Tako first. If its startup log shows `https://0.0.0.0:8001`, run this in another terminal after installing and configuring ngrok:

```console
ngrok http https://localhost:8001
```

Copy ngrok's public **HTTPS forwarding URL**, append `/teams/messages`, and save that URL as the Azure Bot messaging endpoint. Keep both Tako and ngrok running. Match the upstream URL to your actual local scheme and port; use `http://localhost:<port>` if Tako serves plain HTTP.

This integration uses Azure Bot's HTTPS messaging endpoint. Enabling **Streaming Endpoint** does not replace the tunnel or enable Slack-style Socket Mode.

## Part 4 — Enable Teams in Tako

For a Python installation, activate Tako's virtual environment and install the optional integration:

```console
python -m pip install -r requirements-teams.txt
```

For Docker, build an image that includes it:

```console
docker build --build-arg INSTALL_TEAMS_BOT=true -t tako-teams .
```

Set these values in your deployment's environment or local server configuration:

```dotenv
TEAMS_ENABLE=true
TEAMS_TENANT_ID=your-directory-tenant-guid
TEAMS_CLIENT_ID=your-application-client-guid
TEAMS_CLIENT_SECRET=your-client-secret-value
TEAMS_ALLOWED_GROUP_IDS=your-security-group-guid
TEAMS_SESSION_RETENTION_HOURS=24
```

`TEAMS_ENABLE` defaults to `false`. Restart Tako after changing the configuration. With it disabled, the bot endpoint is not mounted. With it enabled, all four identity/access settings are required. **An empty `TEAMS_ALLOWED_GROUP_IDS` does not allow everyone: enabled Teams configuration fails startup until a valid group list is supplied.**

Run **one API worker and one replica** for this initial integration. Keep the database and chat-session directories persistent. When using Docker, pass the environment variables into the running container; the build argument only installs dependencies.

## Part 5 — Build and install the Teams package

Teams accepts a **ZIP containing `manifest.json` and two PNG icons**, not XML.

**Script location:** `<repository-root>/scripts/build_teams_package.py`. The repository root is the `okta-ai-agent` folder you cloned, containing `main.py` and `requirements.txt`. The builder uses the template and icons in `<repository-root>/teams-app/`; keep that folder in place.

Open a terminal in the repository root and run:

```console
python scripts/build_teams_package.py
```

If your terminal is already inside `<repository-root>/scripts/`, run this instead:

```console
python build_teams_package.py
```

Enter your **Entra Application (client) ID** when prompted. From either location, the script creates `<repository-root>/teams-app/output/Tako-AI-Teams-<client-id>.zip` and prints its full path and upload instructions. Only Python is needed; there are no additional builder dependencies. You can also copy the whole folder elsewhere and run `python build.py` inside it.

For an unattended build or a custom destination, use:

```console
python scripts/build_teams_package.py --client-id YOUR-CLIENT-GUID --output path/to/Tako-AI-Teams.zip
```

When upgrading an app that used a custom Teams app ID, pass `--app-id YOUR-EXISTING-TEAMS-APP-GUID` as well. The builder otherwise derives a stable Teams app ID from your client ID.

The bundled icons already have the required sizes. The template supplies the personal-chat scope and supported commands. The package never includes your client secret.

Website, privacy, and terms URLs are required by the [Teams manifest schema](https://developer.microsoft.com/json-schemas/teams/v1.23/MicrosoftTeams.schema.json). Defaults point to Tako's public repository, its Security & Privacy section, and its license. Use `--website`, `--privacy`, and `--terms` to supply your organization's deployment-specific URLs when appropriate. Fctr's hosted-platform policies do not govern customer-deployed Tako.

Import and validate the ZIP in [Teams Developer Portal](https://dev.teams.microsoft.com/). For a permitted test installation, open **Teams → Apps → Manage your apps → Upload an app → Upload a custom app**, select the ZIP, and add it for personal use. If upload is unavailable, ask your Teams administrator to enable it for testing or distribute the package through your organization's app catalog. [Microsoft upload instructions](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/deploy-and-publish/apps-upload)

## Part 6 — Check that it works

Sign in to Teams as a member of the allowed group and open the bot's personal chat:

1. Send **help** to check message delivery and access.
2. Send **status** to see the latest completed data sync information.
3. Ask **List all users of all statuses with their email addresses** to test a query.
4. Reply **Just show their email addresses** to check that a follow-up uses the previous context. If Tako asks a clarification question, answer directly below it.
5. Select **Download CSV**, allow the OneDrive upload, and open the returned file card. Check that the CSV contains the retrieved rows, not only the preview.
6. Select **New Query**, then type a new question to check that it starts without previous context.
7. Send **cancel** while a query is running to stop your request.

Also test with a user outside the allowed groups; the bot should deny access. Use Teams for these checks: Azure's **Test in Web Chat** uses a different channel, which Tako intentionally rejects.

## Part 7 — Conversations and CSV downloads

Type below a result to refine your request or answer a clarification. Tako retains your personal-chat session across server restarts until it expires. **New Query** (or `new`) starts fresh for your next message. The confirmation reads:

> **New session started**
>
> Previous questions and results are no longer part of this session. Type your next question below.

This resets the context used for future questions; it does not delete the messages or result cards already visible in Teams. After a reset, include any details you want Tako to use in your new question.

| Command or action | What it does |
| --- | --- |
| Type a question | Starts a query or continues the current personal-chat session. |
| Reply to a clarification | Supplies the missing details so Tako can continue. |
| **New Query** or `new` | Starts a fresh session for the next question. |
| `help` | Shows the available commands and conversation guidance. |
| `status` | Shows data sync information. |
| `cancel` | Stops your pending or running query. |
| **Download CSV** | Delivers the saved rows for that specific result through the flow below. |

### Download the retrieved data

**Download CSV** exports the saved retrieved rows from that result, without running the query again:

1. Select **Download CSV** on the result you want.
2. Teams asks permission to save that CSV to your OneDrive. Select **Allow** to proceed, or decline to cancel.
3. Tako uploads the file and posts a native file card. Open that card to view or download the CSV.

**Why does downloading require OneDrive consent?** Tako uses Teams' native personal-chat file-delivery flow. That flow first writes the file to your OneDrive and then makes it available through a file card. Microsoft requires consent for that upload. It approves the individual file transfer; it does not grant Tako broad access to read or manage your OneDrive. It is separate from the Entra group check that authorizes your Okta query. [Microsoft file-delivery flow](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/bots-filesv4)

Your work account needs a provisioned OneDrive for Business account. Consent is single-use and expires after one hour; select **Download CSV** again if needed. Declining does not discard your result or end your conversation. Each download remains tied to the requesting user, personal chat, and saved result.

The preview is limited to ten rows and four columns; the CSV contains all retrieved rows and columns. A partial answer remains partial in its CSV. AI can make mistakes. Please validate the data provided.

File delivery requires `supportsFiles=true`, included in package **0.2.0**. No additional Graph file permissions or streaming-endpoint setting are required. [Microsoft Teams file-consent documentation](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/bots-filesv4)

## Part 8 — Session retention and Docker storage

Teams runtime sessions expire after 24 hours of inactivity by default, including when `TEAMS_SESSION_RETENTION_HOURS` is not set. Set it to 1–8760 hours to change retention. Tako checks at startup and hourly, without needing another message. Active requests and downloads are protected; expired session folders, exports, and associated conversation records are removed. This does not remove messages or files already delivered to Teams or OneDrive.

Cleanup runs inside the Python application; no separate cron job is needed. It stops when the container stops or crashes and checks saved timestamps on the next startup. Restarting does not reset the expiry clock. Persist both `DB_DIR` and `CHAT_SESSIONS_DIR` in Docker volumes if conversations should survive container replacement.

Session cleanup also removes local exports and conversation records. It does not delete files already delivered to OneDrive or messages already in Teams. An expired result button asks you to run a new query.

| Data | Where it remains |
| --- | --- |
| Conversation context and saved results | Tako's configured database and session storage, until local retention cleanup |
| Generated CSV before delivery | Local session storage, covered by the same cleanup |
| CSV after an allowed upload | Your OneDrive, subject to your organization's Microsoft 365 retention policies |
| Result and file cards | Teams chat history, subject to your organization's Teams retention policies |

## Troubleshooting

| Problem | Check |
| --- | --- |
| Chat composer is disabled after a package update | Confirm you opened Tako AI for personal use. Compare Teams web with desktop using the same account, then restart the affected client. If both remain disabled, check the app installation and organization policies. The wording “Chat is turned off for this meeting” alone does not identify the cause. |
| Bot does not respond | Tako is running with `TEAMS_ENABLE=true`; the public HTTPS endpoint is reachable; the Teams channel is enabled. Inspect the Tako server log. |
| Message returns HTTP 400 | Check `logs/okta_ai_agent.log` for `Teams incoming rejected` and its reason. Empty or oversized text, incoming files, and unrecognized card actions are rejected. Tako's result buttons and native file-consent replies are supported. Ordinary text with Teams' HTML companion is accepted. No Azure diagnostics setting is needed. |
| Authentication fails | The Entra client ID, Azure Bot Microsoft App ID, and package `botId` match; tenant IDs match; the secret **Value** is correct and unexpired. |
| Access denied | The sender belongs to an allowed Entra group, and the setting contains the group's Object ID. |
| Access cannot be verified | Both Graph application permissions have admin consent, and the server can reach Microsoft identity and Graph endpoints. |
| Package upload fails | Validate the ZIP in Developer Portal; check the icon dimensions, required URLs, and custom-app policy. |
| **Invalid Bot — Please make sure the bot is registered and Teams channel is enabled** | Open Azure Bot → Settings → Channels and enable Microsoft Teams. Confirm it is listed as Healthy, verify the package's `botId` matches the Azure Bot's Microsoft App ID, then retry installation. |
| A follow-up question needs clarification | Reply below with the missing details. Use **New Query** (or type `new`) to start fresh. |
| Download CSV is missing | The button appears on table results containing rows. Restart Tako with the updated backend and update the Teams app package. Older result cards do not gain buttons automatically. |
| CSV cannot be saved to OneDrive | Confirm your work account has OneDrive for Business provisioned and can open it. Confirm the updated package enables file support. Try **Download CSV** again for a new consent request; ask your administrator to inspect the server log if it still fails. |
| Results or download consent have expired | Consent is single-use and lasts one hour. Select **Download CSV** again while the saved result remains available. If the result itself has expired, run a new query. |
