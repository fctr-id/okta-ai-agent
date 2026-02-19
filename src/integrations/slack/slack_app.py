"""
Slack Bolt App - Handles slash commands and app mentions for TakoAI.

This module sets up the Slack Bolt application that listens for:
- /tako slash commands
- @TakoAI app mentions

All queries are processed asynchronously via the multi-agent orchestrator.
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from src.config.settings import settings
from src.core.agents.orchestrator import (
    execute_multi_agent_query,
    OrchestratorResult,
    check_database_health,
    get_last_sync_timestamp,
)
from src.core.okta.client import OktaClient
from src.core.okta.sync.operations import DatabaseOperations
from src.api.routers.sync import run_sync_operation
from src.integrations.slack.event_handler import SlackEventHandler
from src.integrations.slack.formatters import (
    format_error_message,
    format_sync_status_message,
    format_sync_complete_message,
    format_sync_progress_message,
    format_help_message,
    format_history_message,
)
from src.utils.logging import get_logger, set_correlation_id
from src.utils.security_config import validate_generated_code

logger = get_logger("slack_bot")

# Track background tasks to prevent GC
_background_tasks: set = set()


# ============================================================================
# Access Control — Deny by Default
# ============================================================================

async def _check_user_allowed(client: AsyncWebClient, user_id: str) -> bool:
    """
    Check if a Slack user is authorized to use Tako commands.
    
    Returns True if allowed, False if denied.
    
    Strategy:
    1. If no allowlists configured AND SLACK_ALLOW_ALL_USERS is not true → DENY (fail-closed)
    2. Check email allowlist (via users.info API)
    3. Check Slack User Group membership (via usergroups.list + usergroups.users.list)
    4. If no check passes → DENY
    """
    allowed_emails_raw = settings.SLACK_ALLOWED_EMAILS.strip()
    allowed_groups_raw = settings.SLACK_ALLOWED_GROUPS.strip()

    # Deny-by-default: if no allowlists AND no explicit allow-all, reject
    if not allowed_emails_raw and not allowed_groups_raw:
        if settings.SLACK_ALLOW_ALL_USERS:
            return True
        logger.warning(
            f"Slack access denied for {user_id}: no allowlists configured and SLACK_ALLOW_ALL_USERS is not true"
        )
        return False

    # --- Email check ---
    if allowed_emails_raw:
        allowed_emails = {e.strip().lower() for e in allowed_emails_raw.split(",") if e.strip()}
        try:
            user_info = await client.users_info(user=user_id)
            user_email = (user_info["user"].get("profile", {}).get("email") or "").lower()
            if user_email in allowed_emails:
                return True
        except Exception as e:
            logger.warning(f"Failed to fetch user email for {user_id}: {e}")

    # --- Slack User Group check ---
    if allowed_groups_raw:
        allowed_group_names = {g.strip().lower() for g in allowed_groups_raw.split(",") if g.strip()}
        try:
            # Resolve group names to IDs
            groups_response = await client.usergroups_list()
            target_group_ids = []
            for group in groups_response.get("usergroups", []):
                if group.get("handle", "").lower() in allowed_group_names:
                    target_group_ids.append(group["id"])

            # Check membership in each matching group
            for group_id in target_group_ids:
                members_response = await client.usergroups_users_list(usergroup=group_id)
                if user_id in members_response.get("users", []):
                    return True
        except Exception as e:
            logger.warning(f"Failed to check user group membership for {user_id}: {e}")

    return False


def create_slack_app() -> Optional[AsyncApp]:
    """
    Create and configure the Slack Bolt async app.
    Returns None if Slack is not configured.
    """
    if not settings.ENABLE_SLACK_BOT:
        return None

    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_SIGNING_SECRET:
        logger.warning(
            "ENABLE_SLACK_BOT is true but SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET is missing"
        )
        return None

    app = AsyncApp(
        token=settings.SLACK_BOT_TOKEN,
        signing_secret=settings.SLACK_SIGNING_SECRET,
    )

    # ------------------------------------------------------------------
    # Slash command: /tako
    # ------------------------------------------------------------------
    _SUBCOMMANDS = {"sync", "status", "help", "history", "favorites"}

    @app.command("/tako")
    async def handle_tako_command(ack, command, client: AsyncWebClient):
        """Handle /tako slash command with subcommand routing."""
        await ack()

        query = (command.get("text") or "").strip()
        channel_id = command["channel_id"]
        user_id = command["user_id"]

        # Access control gate
        if not await _check_user_allowed(client, user_id):
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":lock: You are not authorized to use Tako. Contact your admin.",
            )
            return

        if not query:
            blocks = format_help_message()
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Tako AI — Slack Commands",
                blocks=blocks,
            )
            return

        # Route subcommands
        first_word = query.split()[0].lower()
        if first_word in _SUBCOMMANDS:
            if first_word == "help":
                blocks = format_help_message()
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text="Tako AI — Slack Commands",
                    blocks=blocks,
                )
                return

            if first_word == "status":
                task = asyncio.create_task(
                    _handle_status(client=client, channel_id=channel_id, user_id=user_id)
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                return

            if first_word == "sync":
                task = asyncio.create_task(
                    _handle_sync(client=client, channel_id=channel_id, user_id=user_id)
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                return

            if first_word == "history":
                task = asyncio.create_task(
                    _handle_history(client=client, channel_id=channel_id, user_id=user_id)
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                return

            if first_word == "favorites":
                task = asyncio.create_task(
                    _handle_favorites(client=client, channel_id=channel_id, user_id=user_id)
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                return

        # Default: treat as a query
        task = asyncio.create_task(
            _process_query(
                client=client,
                channel_id=channel_id,
                user_id=user_id,
                query=query,
                thread_ts=None,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # ------------------------------------------------------------------
    # App mention: @TakoAI <query>
    # ------------------------------------------------------------------
    @app.event("app_mention")
    async def handle_mention(event, client: AsyncWebClient):
        """Handle @TakoAI mentions in channels."""
        text = event.get("text", "")
        channel_id = event.get("channel")
        user_id = event.get("user")
        thread_ts = event.get("thread_ts") or event.get("ts")

        # Access control gate
        if not await _check_user_allowed(client, user_id):
            try:
                await client.reactions_add(channel=channel_id, name="lock", timestamp=event["ts"])
            except Exception:
                pass
            return

        # Strip the bot mention from the text
        # Mentions look like: <@U12345> query text
        query = text.split(">", 1)[-1].strip() if ">" in text else text.strip()

        if not query:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Hi! Ask me anything about your Okta data.\nExample: `@Tako AI list all active users`",
            )
            return

        # Start query processing in background
        task = asyncio.create_task(
            _process_query(
                client=client,
                channel_id=channel_id,
                user_id=user_id,
                query=query,
                thread_ts=thread_ts,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # ------------------------------------------------------------------
    # Button interactions: Star, Unstar, Run from /tako history
    # ------------------------------------------------------------------

    @app.action("tako_star_query")
    async def handle_star_query(ack, action, client: AsyncWebClient, body):
        """Star a query from the history list."""
        await ack()
        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]

        # Re-check access control (user may have been removed since buttons were shown)
        if not await _check_user_allowed(client, user_id):
            await client.chat_postEphemeral(
                channel=channel_id, user=user_id,
                text=":lock: You are no longer authorized to use Tako.",
            )
            return

        try:
            history_id = int(action["value"])
        except (ValueError, TypeError):
            return

        db_ops = DatabaseOperations()
        result = await db_ops.toggle_slack_query_favorite(history_id, user_id, is_favorite=True)
        if result:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":star: Query starred! Use `/tako favorites` to see all starred queries.",
            )
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":x: Could not star query \u2014 maximum 10 favorites reached, or query not found.",
            )

    @app.action("tako_unstar_query")
    async def handle_unstar_query(ack, action, client: AsyncWebClient, body):
        """Unstar a query from the history or favorites list."""
        await ack()
        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]

        if not await _check_user_allowed(client, user_id):
            await client.chat_postEphemeral(
                channel=channel_id, user=user_id,
                text=":lock: You are no longer authorized to use Tako.",
            )
            return

        try:
            history_id = int(action["value"])
        except (ValueError, TypeError):
            return

        db_ops = DatabaseOperations()
        result = await db_ops.toggle_slack_query_favorite(history_id, user_id, is_favorite=False)
        if result:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":white_check_mark: Query unstarred.",
            )
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":x: Could not unstar query \u2014 query not found.",
            )

    @app.action("tako_run_query")
    async def handle_run_query(ack, action, client: AsyncWebClient, body):
        """Re-run a saved query by executing the stored script directly — skips the AI pipeline."""
        await ack()
        user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]

        if not await _check_user_allowed(client, user_id):
            await client.chat_postEphemeral(
                channel=channel_id, user=user_id,
                text=":lock: You are no longer authorized to use Tako.",
            )
            return

        try:
            history_id = int(action["value"])
        except (ValueError, TypeError):
            return

        db_ops = DatabaseOperations()
        item = await db_ops.get_slack_history_item(history_id, user_id)
        if not item:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=":x: Query not found.",
            )
            return
        task = asyncio.create_task(
            _replay_saved_script(
                client=client,
                channel_id=channel_id,
                user_id=user_id,
                query=item.query_text,
                script_code=item.final_script,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    logger.info("Slack Bolt app created successfully")
    return app


# Module-level cache so the same app instance is reused by socket mode
_slack_app_instance: Optional[AsyncApp] = None


def get_or_create_slack_app() -> Optional[AsyncApp]:
    """Return the cached Slack app, creating it on first call."""
    global _slack_app_instance
    if _slack_app_instance is None:
        _slack_app_instance = create_slack_app()
    return _slack_app_instance


async def start_socket_mode() -> None:
    """
    Start the Slack Socket Mode handler.

    Creates an outbound WebSocket connection to Slack's servers — no public
    URL required. Runs until the process exits.

    Called from the FastAPI lifespan when SLACK_OPERATION_MODE=socket.
    """
    if settings.SLACK_OPERATION_MODE != "socket":
        logger.warning("start_socket_mode() called but SLACK_OPERATION_MODE is not 'socket' — skipping")
        return

    app = get_or_create_slack_app()
    if app is None:
        logger.warning("Cannot start Socket Mode: Slack app could not be created")
        return

    app_token = settings.SLACK_APP_TOKEN
    if not app_token or not app_token.startswith("xapp-"):
        logger.error(
            "SLACK_OPERATION_MODE=socket requires SLACK_APP_TOKEN (starts with xapp-). "
            "Generate one at https://api.slack.com/apps → Socket Mode."
        )
        return

    try:
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        handler = AsyncSocketModeHandler(app, app_token)
        logger.info("Starting Slack Socket Mode (outbound WebSocket to Slack)")
        await handler.start_async()
    except ImportError:
        logger.error(
            "Failed to import AsyncSocketModeHandler. "
            "Install with: pip install slack-bolt[async]"
        )
    except Exception as e:
        logger.error(f"Slack Socket Mode error: {e}", exc_info=True)


# ============================================================================
# Query Processing
# ============================================================================

async def _replay_saved_script(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
    query: str,
    script_code: str,
):
    """
    Execute a saved script directly — no AI orchestration. Used by the ▶ Run
    button in /tako history and /tako favorites.

    Skips discovery, planning and code-generation phases entirely.
    """
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    logger.info(f"[{correlation_id}] Replaying saved script for user {user_id}: {query}")

    initial_response = await client.chat_postMessage(
        channel=channel_id,
        text=f":arrows_counterclockwise: Running saved query...\n> {query}",
    )
    message_ts = initial_response["ts"]

    slack_handler = SlackEventHandler(
        slack_client=client,
        channel_id=channel_id,
        thread_ts=message_ts,
        correlation_id=correlation_id,
    )
    slack_handler._progress_message_ts = message_ts

    try:
        # Security validation on the stored script before execution
        validation_result = validate_generated_code(script_code)
        if not validation_result.is_valid:
            violations = ", ".join(validation_result.violations)
            await slack_handler.post_error(f"Security validation failed: {violations}")
            return

        # Execute the script directly — no OrchestratorResult metadata needed
        # Build a minimal result object the same way orchestrator.py does
        minimal_result = OrchestratorResult()
        minimal_result.success = True
        minimal_result.script_code = script_code
        script_results = await _execute_script_for_slack(
            correlation_id, script_code, minimal_result
        )

        if script_results:
            await slack_handler.post_final_results(query, script_results)
            await slack_handler.post_script(script_code)
        else:
            await slack_handler.post_error(
                "Script execution failed. The saved script may reference data that has changed. "
                "Try running the query fresh with `/tako <query>`."
            )
    except Exception as e:
        logger.error(f"[{correlation_id}] Error replaying saved script: {e}", exc_info=True)
        await slack_handler.post_error("An internal error occurred. Please try again.")


async def _process_query(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
    query: str,
    thread_ts: Optional[str],
):
    """
    Execute a TakoAI query and post results to Slack.

    This runs as a background task after the Slack command is acknowledged.
    It mirrors the flow in react_stream.py but adapted for Slack output.
    """
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    logger.info(f"[{correlation_id}] Slack query from user {user_id}: {query}")

    # Post initial message (creates the thread if needed)
    initial_response = await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":hourglass_flowing_sand: Processing your query...\n> {query}",
    )
    message_thread_ts = initial_response["ts"] if not thread_ts else thread_ts

    # Create event handler for Slack
    slack_handler = SlackEventHandler(
        slack_client=client,
        channel_id=channel_id,
        thread_ts=message_thread_ts,
        correlation_id=correlation_id,
    )
    slack_handler._progress_message_ts = initial_response["ts"]

    try:
        # Pre-query database health check — warn but don't block
        db_healthy = check_database_health()
        if not db_healthy:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=message_thread_ts,
                text=(
                    ":warning: No synced Okta data found. Queries may return incomplete results.\n"
                    "Run `/tako sync` to sync your Okta data."
                ),
            )

        # Create artifacts file (same pattern as react_stream.py)
        artifacts_dir = Path("logs").resolve()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifacts_file = artifacts_dir / f"artifacts_{correlation_id}.json"
        with open(artifacts_file, "w", encoding="utf-8") as f:
            json.dump([], f)

        # Create Okta client
        okta_client = OktaClient()

        def check_cancelled():
            return False

        # Event callback that bridges to SlackEventHandler
        async def event_callback(event_type: str, event_data: Dict[str, Any]):
            await slack_handler.handle_event(event_type, event_data)

        # Run the multi-agent orchestrator
        result: OrchestratorResult = await execute_multi_agent_query(
            user_query=query,
            correlation_id=correlation_id,
            artifacts_file=artifacts_file,
            okta_client=okta_client,
            cancellation_check=check_cancelled,
            event_callback=event_callback,
        )

        # Store token usage for final message
        if result.total_tokens > 0:
            slack_handler.set_token_usage({
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "total_tokens": result.total_tokens,
            })

        # Handle failures
        if not result.success:
            error_msg = result.error or "Query execution failed"

            # NOT_RELEVANT special case
            if error_msg == "NOT-OKTA-RELATED":
                error_msg = (
                    "This query doesn't appear to be related to Okta. "
                    "Please ask about Okta users, groups, apps, or policies."
                )

            await slack_handler.post_error(error_msg)
            return

        # Handle no data found
        if result.no_data_found:
            no_data_content = "## No Results Found\n\nYour query completed successfully, but no matching data was found."
            if not db_healthy:
                no_data_content += "\n\n:bulb: *Tip:* Your local database has no synced data. Run `/tako sync` to populate it."
            await slack_handler.post_final_results(query, {
                "display_type": "markdown",
                "content": no_data_content,
            })
            return

        # Handle special tools (summaries, modifications)
        if result.is_special_tool:
            await slack_handler.post_final_results(query, {
                "display_type": result.display_type or "markdown",
                "content": result.script_code,
            })
            await _save_history(correlation_id, query, "", user_id, channel_id=channel_id, thread_ts=message_thread_ts)
            return

        # No script generated
        if not result.script_code:
            await slack_handler.post_error(
                "Synthesis agent completed but failed to generate executable code. "
                "Please try rephrasing your query."
            )
            return

        # Validate generated code
        validation_result = validate_generated_code(result.script_code)
        if not validation_result.is_valid:
            violations = ", ".join(validation_result.violations)
            await slack_handler.post_error(f"Security validation failed: {violations}")
            return

        # Execute the generated script
        script_results = await _execute_script_for_slack(
            correlation_id, result.script_code, result
        )

        if script_results:
            await slack_handler.post_final_results(query, script_results)
            await slack_handler.post_script(result.script_code)
            await _save_history(
                correlation_id, query, result.script_code, user_id,
                channel_id=channel_id, thread_ts=message_thread_ts
            )
        else:
            await slack_handler.post_error("Script execution failed. Check logs for details.")

    except Exception as e:
        logger.error(f"[{correlation_id}] Slack query processing error: {e}", exc_info=True)
        await slack_handler.post_error("An internal error occurred. Please try again later.")


# ============================================================================
# Subcommand Handlers
# ============================================================================

class _ReusableSessionFactory:
    """
    Wraps an async_sessionmaker so that each ``async with instance as session:``
    creates a **new** AsyncSession.

    ``run_sync_operation`` re-enters ``async with db_session as session:``
    multiple times (for RUNNING, COMPLETED, FAILED updates).  A bare
    AsyncSession closes after the first exit, silently breaking subsequent
    entries.  This wrapper delegates each entry to a fresh session.
    """

    def __init__(self, session_factory):
        self._factory = session_factory
        self._current = None

    async def __aenter__(self):
        self._current = self._factory()
        return await self._current.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._current is not None:
            result = await self._current.__aexit__(exc_type, exc_val, exc_tb)
            self._current = None
            return result


async def _handle_status(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
):
    """Handle /tako status — show DB health and last sync info."""
    try:
        db_healthy = check_database_health()
        last_sync = get_last_sync_timestamp()

        # Check for active sync and get entity counts
        db_ops = DatabaseOperations()
        tenant_id = settings.tenant_id
        active_sync_info = None
        entity_counts = None

        try:
            await db_ops.init_db()
            async with db_ops.get_session() as session:
                active_sync = await db_ops.get_active_sync(session, tenant_id)
                if active_sync:
                    active_sync_info = {"progress": active_sync.progress_percentage or 0}

                # Get entity counts from last completed sync
                last_completed = await db_ops.get_last_completed_sync(session, tenant_id)
                if last_completed:
                    entity_counts = {
                        "users": last_completed.users_count or 0,
                        "groups": last_completed.groups_count or 0,
                        "applications": last_completed.apps_count or 0,
                    }
        except Exception as e:
            logger.debug(f"Could not query sync details for status: {e}")

        blocks = format_sync_status_message(
            db_healthy=db_healthy,
            last_sync=last_sync,
            active_sync=active_sync_info,
            entity_counts=entity_counts,
        )
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Tako AI — Status",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Error handling /tako status: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=":x: Failed to retrieve status. Check server logs.",
        )


async def _handle_history(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
):
    """Handle /tako history \u2014 show last 5 queries with Run & Star buttons."""
    try:
        db_ops = DatabaseOperations()
        items = await db_ops.get_slack_query_history(slack_user_id=user_id, limit=5)
        blocks = format_history_message(items, title="Recent Queries (last 5)")
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Tako AI \u2014 History",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Error handling /tako history: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=":x: Failed to retrieve history. Check server logs.",
        )


async def _handle_favorites(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
):
    """Handle /tako favorites \u2014 show starred queries with Run & Unstar buttons."""
    try:
        db_ops = DatabaseOperations()
        items = await db_ops.get_slack_query_history(
            slack_user_id=user_id, limit=10, favorites_only=True
        )
        blocks = format_history_message(items, title="Favorite Queries")
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Tako AI \u2014 Favorites",
            blocks=blocks,
        )
    except Exception as e:
        logger.error(f"Error handling /tako favorites: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=":x: Failed to retrieve favorites. Check server logs.",
        )


async def _handle_sync(
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
):
    """Handle /tako sync — trigger an Okta data sync from Slack."""
    db_ops = DatabaseOperations()
    tenant_id = settings.tenant_id

    try:
        # Ensure tables exist (critical for first-ever sync)
        await db_ops.init_db()

        async with db_ops.get_session() as session:
            # Guard against concurrent syncs
            active_sync = await db_ops.get_active_sync(session, tenant_id)
            if active_sync:
                progress = active_sync.progress_percentage or 0
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f":arrows_counterclockwise: A sync is already running ({progress}% complete).",
                )
                return

            # Create sync history record
            sync_history = await db_ops.create_sync_history(session, tenant_id)
            sync_id = sync_history.id

        # Post visible "starting" message to channel
        msg_response = await client.chat_postMessage(
            channel=channel_id,
            text=format_sync_progress_message("Starting Okta sync..."),
        )
        progress_ts = msg_response["ts"]

        # Launch the sync operation as a background task.
        # run_sync_operation uses `async with db_session as session:` multiple
        # times, so it needs a wrapper that creates a fresh AsyncSession on
        # each context-manager entry (a bare AsyncSession closes after the
        # first exit and subsequent entries silently fail).
        sync_session = _ReusableSessionFactory(db_ops.SessionLocal)
        sync_task = asyncio.create_task(
            run_sync_operation(sync_id, sync_session)
        )
        _background_tasks.add(sync_task)
        sync_task.add_done_callback(_background_tasks.discard)

        # Poll for completion and update the Slack message
        await _poll_sync_progress(
            client=client,
            channel_id=channel_id,
            progress_ts=progress_ts,
            sync_id=sync_id,
            db_ops=db_ops,
            tenant_id=tenant_id,
            sync_task=sync_task,
        )

    except Exception as e:
        logger.error(f"Error handling /tako sync: {e}", exc_info=True)
        await client.chat_postMessage(
            channel=channel_id,
            text=f":x: Failed to start sync: {e}",
        )


async def _poll_sync_progress(
    client: AsyncWebClient,
    channel_id: str,
    progress_ts: str,
    sync_id: int,
    db_ops: DatabaseOperations,
    tenant_id: str,
    sync_task: asyncio.Task,
):
    """Poll sync progress and update a Slack message until complete."""
    last_progress = -1

    while not sync_task.done():
        await asyncio.sleep(10)

        try:
            async with db_ops.get_session() as session:
                active = await db_ops.get_active_sync(session, tenant_id)
                if active and active.id == sync_id:
                    progress = active.progress_percentage or 0
                    if progress != last_progress:
                        last_progress = progress
                        await client.chat_update(
                            channel=channel_id,
                            ts=progress_ts,
                            text=format_sync_progress_message("Syncing", progress),
                        )
        except Exception as e:
            logger.debug(f"Error polling sync progress: {e}")

    # Sync task is done — get final results
    try:
        async with db_ops.get_session() as session:
            last_sync = await db_ops.get_last_completed_sync(session, tenant_id)
            if last_sync and last_sync.success:
                entity_counts = {
                    "users": last_sync.users_count or 0,
                    "groups": last_sync.groups_count or 0,
                    "applications": last_sync.apps_count or 0,
                }
                # Update progress message to complete
                await client.chat_update(
                    channel=channel_id,
                    ts=progress_ts,
                    text=":white_check_mark: Okta sync completed.",
                )
                # Post summary
                blocks = format_sync_complete_message(entity_counts)
                await client.chat_postMessage(
                    channel=channel_id,
                    text="Okta Sync Complete",
                    blocks=blocks,
                )
            else:
                error_detail = ""
                if last_sync and last_sync.error_details:
                    error_detail = f"\n{last_sync.error_details}"
                await client.chat_update(
                    channel=channel_id,
                    ts=progress_ts,
                    text=f":x: Okta sync failed.{error_detail}",
                )
    except Exception as e:
        logger.error(f"Error posting sync results: {e}", exc_info=True)
        await client.chat_update(
            channel=channel_id,
            ts=progress_ts,
            text=":x: Sync finished but failed to retrieve results.",
        )


async def _execute_script_for_slack(
    correlation_id: str,
    script_code: str,
    orchestrator_result: OrchestratorResult,
) -> Optional[Dict[str, Any]]:
    """
    Execute a generated script and return parsed results.
    Mirrors _execute_script / _write_temp_script from react_stream.py.
    """
    import shutil

    script_path = None
    try:
        project_root = Path(__file__).parent.parent.parent.parent
        temp_dir = project_root / "generated_scripts"
        temp_dir.mkdir(parents=True, exist_ok=True)

        script_path = temp_dir / f"slack_execution_{correlation_id}.py"

        # Security check — prevent path traversal
        import os
        normalized_script = os.path.normpath(str(script_path))
        normalized_temp = os.path.normpath(str(temp_dir))
        if not normalized_script.startswith(normalized_temp + os.sep):
            raise ValueError("Invalid script path - potential path traversal")

        # Copy API client helper if needed
        if "base_okta_api_client" in script_code or "OktaAPIClient" in script_code:
            api_client_source = (
                project_root / "src" / "core" / "okta" / "client" / "base_okta_api_client.py"
            )
            api_client_dest = temp_dir / "base_okta_api_client.py"
            if api_client_source.exists():
                shutil.copy2(api_client_source, api_client_dest)

        # Rewrite imports for standalone execution
        modified_code = script_code.replace(
            "from src.core.okta.client.base_okta_api_client import OktaAPIClient",
            "from base_okta_api_client import OktaAPIClient",
        )

        with open(script_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(modified_code)

        # Detect Python executable
        venv_python = Path("venv/Scripts/python.exe")
        python_exe = str(venv_python) if venv_python.exists() else "python"

        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",
            script_path.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(temp_dir),
            limit=1024 * 1024,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=120
        )

        if proc.returncode != 0:
            error_msg = stderr_bytes.decode("utf-8", errors="replace")[-500:]
            logger.error(f"[{correlation_id}] Slack script execution failed: {error_msg}")
            return None

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        results_data = _parse_script_output(stdout_str)

        if not results_data:
            return None

        # Build event_data in same format as react_stream.py COMPLETE events
        if results_data.get("display_type") == "markdown":
            return {
                "display_type": "markdown",
                "content": results_data.get("content", ""),
            }

        if results_data.get("count", 0) == 0:
            return {
                "display_type": "markdown",
                "content": "## No Results Found\n\nYour query completed successfully, but no matching data was found.",
            }

        # Build metadata
        metadata = {}
        if orchestrator_result.data_source_type:
            metadata["data_source_type"] = orchestrator_result.data_source_type
            if (
                orchestrator_result.data_source_type in ["sql", "hybrid"]
                and orchestrator_result.last_sync_time
            ):
                metadata["last_sync"] = {"last_sync": orchestrator_result.last_sync_time}

        return {
            "display_type": results_data.get("display_type", "table"),
            "results": results_data.get("data", []),
            "headers": results_data.get("headers", []),
            "count": results_data.get("count", 0),
            "metadata": metadata,
        }

    except asyncio.TimeoutError:
        logger.error(f"[{correlation_id}] Script execution timed out")
        return None
    except Exception as e:
        logger.error(f"[{correlation_id}] Script execution error: {e}", exc_info=True)
        return None
    finally:
        # Clean up temp script — it's already uploaded to Slack thread by post_script()
        try:
            if script_path and script_path.exists():
                script_path.unlink()
                logger.debug(f"[{correlation_id}] Cleaned up temp script: {script_path}")
        except Exception:
            pass


def _parse_script_output(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse JSON results from script stdout (same logic as react_stream.py)."""
    try:
        lines = stdout.split("\n")
        json_lines = []
        in_json = False

        for line in lines:
            if line.strip() == "QUERY RESULTS":
                in_json = True
                continue
            elif line.strip().startswith("====") and in_json and json_lines:
                break
            elif in_json and line.strip() and not line.strip().startswith("===="):
                json_lines.append(line)

        if json_lines:
            json_text = "\n".join(json_lines)
            parsed_output = json.loads(json_text)

            if isinstance(parsed_output, list):
                return {
                    "display_type": "table",
                    "data": parsed_output,
                    "count": len(parsed_output),
                }
            elif isinstance(parsed_output, dict):
                return parsed_output

    except Exception as e:
        logger.warning(f"Failed to parse Slack script output: {e}")
        return None

    return None


async def _save_history(
    correlation_id: str,
    query: str,
    script_code: str,
    user_id: str,
    channel_id: str = "",
    thread_ts: str = "",
):
    """Save query to history database."""
    try:
        db_ops = DatabaseOperations()
        summary = f"Slack query by {user_id}"
        await db_ops.save_query_history(
            tenant_id=settings.tenant_id,
            user_id=f"slack:{user_id}",
            query_text=query,
            final_script=script_code,
            results_summary=summary,
            source="slack",
            slack_user_id=user_id,
            slack_channel_id=channel_id,
            slack_thread_ts=thread_ts,
        )
        logger.info(f"[{correlation_id}] Slack query history saved")
    except Exception as e:
        logger.error(f"[{correlation_id}] Failed to save Slack query history: {e}")
