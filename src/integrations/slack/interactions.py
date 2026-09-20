"""Conversation reply and result-button handlers for the Slack adapter."""
import asyncio
from collections import OrderedDict
import json
import time

from src.integrations.slack import sessions
from src.integrations.slack.formatters import results_to_csv_string


def result_actions(reference, *, has_csv):
    buttons = [{"type": "button", "text": {"type": "plain_text", "text": "New Query"},
                "action_id": "tako_new_query", "value": reference}]
    if has_csv:
        buttons.append({"type": "button", "text": {"type": "plain_text", "text": "Download CSV"},
                        "action_id": "tako_download_csv", "value": reference})
    return [
        {"type": "actions", "elements": buttons},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            "Want to refine these results or ask a follow-up question? Reply in this thread."}]},
    ]


def register_conversation_handlers(app, *, check_access, process_query, background_tasks):
    seen = OrderedDict()

    def start(coroutine):
        task = asyncio.create_task(coroutine)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    async def notice(client, channel, user, text):
        await client.chat_postEphemeral(channel=channel, user=user, text=text)

    @app.event("message")
    async def follow_up(event, client, context):
        # Only original human replies in a thread already owned by this user.
        if event.get("subtype") or event.get("bot_id") or not event.get("thread_ts"):
            return
        user, channel, thread = event.get("user"), event.get("channel"), event["thread_ts"]
        text = (event.get("text") or "").strip()
        if not user or not channel or not text:
            return
        # Mentions have their own event handler; don't run the same message twice.
        bot = context.get("bot_user_id")
        if bot and f"<@{bot}>" in text:
            return
        if not sessions.has_thread(user, channel, thread):
            return
        key = (channel, event.get("ts"))
        now = time.time()
        while seen and (next(iter(seen.values())) < now - 86400 or len(seen) >= 10000):
            seen.popitem(last=False)
        if key in seen:
            return
        seen[key] = now
        if not await check_access(client, user):
            await notice(client, channel, user, "You are not authorized to use Tako. Contact your admin.")
            return
        start(process_query(client=client, channel_id=channel, user_id=user, query=text, thread_ts=thread))

    async def owned_turn(body, action, client):
        user = body["user"]["id"]
        channel = body["channel"]["id"]
        if not await check_access(client, user):
            await notice(client, channel, user, "You are no longer authorized to use Tako.")
            return None
        saved = await sessions.get_saved_turn(user, action.get("value", ""), channel)
        if not saved:
            await notice(client, channel, user, "These results have expired or are unavailable. Start again with /tako <question>.")
        return saved

    @app.action("tako_download_csv")
    async def download(ack, action, client, body):
        await ack()
        # Keep the event acknowledgment fast; export only saved rows, never rerun AI.
        async def deliver():
            saved = await owned_turn(body, action, client)
            if not saved:
                return
            path, metadata = saved
            try:
                async with sessions.reserve_thread(body["user"]["id"], body["channel"]["id"], metadata["thread_ts"]) as acquired:
                    if not acquired:
                        await notice(client, body["channel"]["id"], body["user"]["id"], "This thread is busy. Please try downloading again when it finishes.")
                        return
                    payload = json.loads((path / "results" / "slack_response.json").read_text(encoding="utf-8"))
                    rows = payload.get("results", [])
                    if not rows or payload.get("display_type") == "markdown":
                        await notice(client, body["channel"]["id"], body["user"]["id"], "This response has no tabular data to download.")
                        return
                    await client.files_upload_v2(
                        channel=body["channel"]["id"], thread_ts=metadata["thread_ts"],
                        content=results_to_csv_string(rows, payload.get("headers", [])),
                        filename="tako_results.csv", title="Retrieved results (CSV)",
                        initial_comment=f"{len(rows):,} retrieved records. AI can make mistakes. Please validate the data provided.",
                    )
            except Exception:
                from src.utils.logging import get_logger
                get_logger("slack_sessions").exception("Slack CSV delivery failed")
                await notice(client, body["channel"]["id"], body["user"]["id"], "Could not deliver the CSV. Please try again.")
        start(deliver())

    @app.action("tako_new_query")
    async def new_query(ack, action, client, body):
        await ack()
        if not await owned_turn(body, action, client):
            return
        await client.views_open(trigger_id=body["trigger_id"], view={
            "type": "modal", "callback_id": "tako_new_query_submit",
            "private_metadata": action["value"],
            "title": {"type": "plain_text", "text": "New Query"},
            "submit": {"type": "plain_text", "text": "Ask"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{"type": "input", "block_id": "question",
                        "label": {"type": "plain_text", "text": "Question"},
                        "element": {"type": "plain_text_input", "action_id": "text", "multiline": True, "max_length": 3000}}],
        })

    @app.view("tako_new_query_submit")
    async def submit(ack, body, view, client):
        query = (view["state"]["values"]["question"]["text"].get("value") or "").strip()
        if not query:
            await ack(response_action="errors", errors={"question": "Enter a question."})
            return
        await ack()
        async def run():
            user = body["user"]["id"]
            if not await check_access(client, user):
                return
            saved = await sessions.get_saved_turn(user, view.get("private_metadata", ""))
            if saved:
                # A fresh top-level message produces a new session; old threads remain.
                await process_query(client=client, channel_id=saved[1]["channel_id"],
                                    user_id=user, query=query, thread_ts=None)
        start(run())
