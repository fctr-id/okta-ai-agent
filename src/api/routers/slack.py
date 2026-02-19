"""
Slack Router - Handles incoming Slack events and slash commands.

This router mounts the Slack Bolt request handler into FastAPI.
All Slack events (slash commands, mentions, interactions) are
dispatched through a single /slack/events endpoint.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.utils.logging import get_logger

logger = get_logger("slack_router")

router = APIRouter(tags=["slack"])


def mount_slack_routes(router_instance: APIRouter):
    """
    Mount Slack Bolt event handler routes.

    Called from main.py when ENABLE_SLACK_BOT is true.
    Uses the Slack Bolt FastAPI adapter to forward requests.
    """
    try:
        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
        from src.integrations.slack.slack_app import get_or_create_slack_app

        slack_app = get_or_create_slack_app()
        if slack_app is None:
            logger.warning("Slack app creation returned None - bot disabled")
            return

        handler = AsyncSlackRequestHandler(slack_app)

        @router_instance.post("/slack/events")
        async def slack_events(request: Request):
            """Handle all Slack events (slash commands, mentions, interactions)."""
            return await handler.handle(request)

        @router_instance.post("/slack/interactions")
        async def slack_interactions(request: Request):
            """Handle Slack interactive components (buttons, modals)."""
            return await handler.handle(request)

        logger.info("Slack routes mounted: /slack/events, /slack/interactions")

    except ImportError as e:
        logger.error(
            f"Failed to import Slack dependencies: {e}. "
            "Install with: pip install slack-bolt slack-sdk"
        )
    except Exception as e:
        logger.error(f"Failed to mount Slack routes: {e}", exc_info=True)
