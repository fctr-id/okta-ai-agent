# Slack conversations and result downloads

Tako shows a ten-row result preview. Reply in the result thread to refine the question or answer a clarification. Each user's conversation is isolated by channel and thread.

- **New Query** opens a question dialog and starts a fresh thread without previous context. `/tako <question>` also starts fresh.
- **Download CSV** uploads the saved retrieved rows into the same thread. It does not rerun the query. The button appears for table results with rows.
- The footer says: “Want to refine these results or ask a follow-up question? Reply in this thread.”

The CSV contains the retrieved result, including any reported partial results; it does not guarantee completeness. AI can make mistakes. Please validate the data provided.

## Enable replies and buttons

For an existing Slack app, add the following under **OAuth & Permissions → Bot Token Scopes** and **Event Subscriptions → Subscribe to bot events**:

| Conversation type | Bot scope | Bot event |
|---|---|---|
| Public channels | `channels:history` | `message.channels` |
| Private channels, if needed | `groups:history` | `message.groups` |
| Direct messages, if needed | `im:history` | `message.im` |
| Group direct messages, if needed | `mpim:history` | `message.mpim` |

Keep `app_mentions:read` and the `app_mention` event. Mentioning Tako in a result thread also supports follow-ups. Plain replies require the matching message subscription above. The bot only processes original human replies in its existing user-owned threads; it ignores unrelated messages, edits, and bot messages. These subscriptions do not create a general direct-message query handler: use `/tako` to start a query.

Keep the existing `chat:write`, `files:write`, and `commands` scopes and the scopes needed for your configured user/group allowlists. **Reinstall the app to the workspace after changing scopes.** The bot must be a member of channels where it is used.

Enable **Interactivity & Shortcuts** for the result buttons and question dialog:

- **Socket Mode:** interactions and events use the existing connection; no public request URL is needed.
- **HTTP mode:** use `https://<your-server>/slack/interactions` for interactivity and `https://<your-server>/slack/events` for events.

Access is checked again for follow-ups and button actions. Downloads belong to the original requesting user and channel. Another user cannot use a button to retrieve that user's local result.

See Slack's [message event documentation](https://docs.slack.dev/reference/events/message/) for subscriptions and scopes.

## Session retention

```env
# Optional: defaults to 24 hours of inactivity. Valid range: 1–8760.
SLACK_SESSION_RETENTION_HOURS=24
```

Restart Tako after changing configuration. Cleanup runs at startup and hourly in both Socket and HTTP modes, with active queries and downloads protected. It removes expired local session folders, saved results, and their conversation database records. Downloads may expire; the button then asks you to start a new query.

When a container is stopped or crashes, cleanup stops too. The next startup checks the saved timestamps. Keep `CHAT_SESSIONS_DIR` and `DB_DIR` on persistent Docker volumes to retain context across container replacement.

Cleanup does not delete messages or files already uploaded to Slack, or query history/favorites. Old thread messages remain visible after their local context expires. Start a new query when that context is no longer available.
