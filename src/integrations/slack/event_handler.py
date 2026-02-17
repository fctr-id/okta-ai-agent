"""
Slack Event Handler - Bridges orchestrator events to Slack messages.

Receives streaming events from the multi-agent orchestrator and posts
progress updates and final results to a Slack thread.
"""

import asyncio
import time
from typing import Dict, Any, Optional, List

from src.utils.logging import get_logger
from src.integrations.slack.formatters import (
    format_progress_message,
    format_error_message,
    format_complete_response,
    results_to_csv_string,
)

logger = get_logger("slack_event_handler")


class SlackEventHandler:
    """
    Converts orchestrator events into Slack messages.

    Slack's 3-second response window requires immediate acknowledgment.
    This handler runs in the background and posts updates to a Slack thread
    using the Slack Web API client.
    """

    def __init__(
        self,
        slack_client,
        channel_id: str,
        thread_ts: str,
        correlation_id: str,
    ):
        self.client = slack_client
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.correlation_id = correlation_id
        self._progress_message_ts: Optional[str] = None
        self._token_usage: Optional[Dict[str, Any]] = None
        self._last_update_time: float = 0
        # Minimum interval between Slack API calls for progress updates
        self._update_interval = 2.0

    async def handle_event(self, event_type: str, event_data: Dict[str, Any]):
        """
        Route an orchestrator event to the appropriate Slack message handler.
        """
        try:
            if event_type == "step_start":
                await self._handle_step_start(event_data)
            elif event_type == "step_end":
                await self._handle_step_end(event_data)
            elif event_type == "progress":
                await self._handle_progress(event_data)
            elif event_type == "tool_call":
                await self._handle_tool_call(event_data)
        except Exception as e:
            logger.error(
                f"[{self.correlation_id}] Error handling Slack event {event_type}: {e}",
                exc_info=True,
            )

    async def post_initial_message(self, query: str) -> str:
        """
        Post the initial "Processing..." message to Slack.
        Returns the thread timestamp for follow-up messages.
        """
        response = await asyncio.to_thread(
            self.client.chat_postMessage,
            channel=self.channel_id,
            thread_ts=self.thread_ts,
            text=f":hourglass_flowing_sand: Processing your query...\n> {query}",
        )
        self._progress_message_ts = response["ts"]
        return response["ts"]

    async def post_final_results(self, query: str, event_data: Dict[str, Any]):
        """Post the final formatted results to the Slack thread."""
        blocks = format_complete_response(
            query=query,
            event_data=event_data,
            token_usage=self._token_usage,
        )

        # Post as a new message in the thread
        await asyncio.to_thread(
            self.client.chat_postMessage,
            channel=self.channel_id,
            thread_ts=self.thread_ts,
            text="Query results",
            blocks=blocks,
        )

        # Upload CSV for large table results
        results = event_data.get("results", [])
        if event_data.get("display_type") != "markdown" and len(results) > 10:
            await self._upload_csv(results, event_data.get("headers", []))

        # Update the progress message to show completion
        if self._progress_message_ts:
            await asyncio.to_thread(
                self.client.chat_update,
                channel=self.channel_id,
                ts=self._progress_message_ts,
                text=f":white_check_mark: Query completed.\n> {query}",
            )

    async def post_error(self, error: str):
        """Post an error message to the Slack thread."""
        blocks = format_error_message(error)
        await asyncio.to_thread(
            self.client.chat_postMessage,
            channel=self.channel_id,
            thread_ts=self.thread_ts,
            text=f"Error: {error}",
            blocks=blocks,
        )

        # Update progress message
        if self._progress_message_ts:
            await asyncio.to_thread(
                self.client.chat_update,
                channel=self.channel_id,
                ts=self._progress_message_ts,
                text=":x: Query failed.",
            )

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    async def _handle_step_start(self, event_data: Dict[str, Any]):
        """Update the progress message with the current step."""
        title = event_data.get("title", "Processing")
        text = event_data.get("text", "")

        # Rate-limit progress updates to avoid Slack API throttling
        now = time.time()
        if now - self._last_update_time < self._update_interval:
            return

        self._last_update_time = now

        if self._progress_message_ts:
            await asyncio.to_thread(
                self.client.chat_update,
                channel=self.channel_id,
                ts=self._progress_message_ts,
                text=f":arrows_counterclockwise: *{title}*: {text}",
            )

    async def _handle_step_end(self, event_data: Dict[str, Any]):
        """Optionally log step completion (kept lightweight)."""
        pass

    async def _handle_progress(self, event_data: Dict[str, Any]):
        """Handle progress events (rate-limited)."""
        message = event_data.get("message", "")
        if not message:
            return

        now = time.time()
        if now - self._last_update_time < self._update_interval:
            return

        self._last_update_time = now

        if self._progress_message_ts:
            await asyncio.to_thread(
                self.client.chat_update,
                channel=self.channel_id,
                ts=self._progress_message_ts,
                text=f":arrows_counterclockwise: {message}",
            )

    async def _handle_tool_call(self, event_data: Dict[str, Any]):
        """Tool call events are logged but not posted to Slack."""
        logger.debug(
            f"[{self.correlation_id}] Tool call: {event_data.get('tool_name')}"
        )

    def set_token_usage(self, usage: Dict[str, Any]):
        """Store token usage for inclusion in the final response."""
        self._token_usage = usage

    async def _upload_csv(self, results: List[Dict[str, Any]], headers: List[str]):
        """Upload full results as a CSV file snippet to the thread."""
        try:
            csv_content = results_to_csv_string(results, headers)
            await asyncio.to_thread(
                self.client.files_upload_v2,
                channel=self.channel_id,
                thread_ts=self.thread_ts,
                content=csv_content,
                filename=f"tako_results_{self.correlation_id[:8]}.csv",
                title="Full Results (CSV)",
                initial_comment=f":floppy_disk: Full results ({len(results)} records)",
            )
        except Exception as e:
            logger.warning(
                f"[{self.correlation_id}] Failed to upload CSV to Slack: {e}"
            )
