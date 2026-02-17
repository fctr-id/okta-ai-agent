"""
Slack Block Kit formatters for TakoAI query results.

Converts orchestrator output (tables, markdown, errors) into
Slack-compatible Block Kit message payloads.
"""

from typing import Dict, Any, List, Optional
import csv
import io


# Slack message character limits
MAX_TEXT_LENGTH = 3000
MAX_SECTION_TEXT = 3000
MAX_BLOCKS = 50


def format_progress_message(title: str, text: str) -> List[Dict[str, Any]]:
    """Format a progress update as Slack blocks."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{title}*\n{text}"
            }
        }
    ]


def format_error_message(error: str) -> List[Dict[str, Any]]:
    """Format an error message as Slack blocks."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: *Error*\n{_truncate(error, MAX_SECTION_TEXT)}"
            }
        }
    ]


def format_markdown_result(content: str) -> List[Dict[str, Any]]:
    """Format a markdown result (special tools, summaries) as Slack blocks."""
    # Convert common markdown to Slack mrkdwn
    slack_text = _markdown_to_slack(content)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _truncate(slack_text, MAX_SECTION_TEXT)
            }
        }
    ]


def format_table_result(
    results: List[Dict[str, Any]],
    headers: List[str],
    count: int,
    metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Format tabular results as Slack blocks.

    For small result sets (<=10 rows), renders an inline table.
    For larger sets, shows a summary with a CSV attachment hint.
    """
    blocks: List[Dict[str, Any]] = []

    # Header with count
    summary_parts = [f":bar_chart: *Results* ({count} records)"]
    if metadata:
        source = metadata.get("data_source_type")
        if source:
            summary_parts.append(f"Source: {source.upper()}")
        last_sync = metadata.get("last_sync", {}).get("last_sync")
        if last_sync:
            summary_parts.append(f"Last sync: {last_sync}")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": " | ".join(summary_parts)
        }
    })

    # Table display (inline for small sets)
    if count > 0 and results:
        table_text = _build_table_text(results, headers, max_rows=10)
        if table_text:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```\n{_truncate(table_text, MAX_SECTION_TEXT - 10)}\n```"
                }
            })

        if count > 10:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Showing first 10 of {count} results._"
                    }
                ]
            })

    return blocks


def format_complete_response(
    query: str,
    event_data: Dict[str, Any],
    token_usage: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Build the final response blocks for a completed query.
    """
    blocks: List[Dict[str, Any]] = []

    display_type = event_data.get("display_type", "table")

    if display_type == "markdown":
        content = event_data.get("content", "")
        blocks.extend(format_markdown_result(content))
    else:
        results = event_data.get("results", [])
        headers = event_data.get("headers", [])
        count = event_data.get("count", 0)
        metadata = event_data.get("metadata")
        blocks.extend(format_table_result(results, headers, count, metadata))

    # Token usage footer
    if token_usage and token_usage.get("total_tokens", 0) > 0:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f":coin: Tokens: {token_usage['total_tokens']:,} "
                        f"({token_usage.get('input_tokens', 0):,} in / "
                        f"{token_usage.get('output_tokens', 0):,} out)"
                    )
                }
            ]
        })

    return blocks[:MAX_BLOCKS]


def format_sync_status_message(
    db_healthy: bool,
    last_sync: Optional[str],
    active_sync: Optional[Dict[str, Any]] = None,
    entity_counts: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """Format database/sync status as Slack blocks (ephemeral response)."""
    blocks: List[Dict[str, Any]] = []

    # Database health line
    if db_healthy:
        user_count = (entity_counts or {}).get("users", 0)
        db_text = f":white_check_mark: *Database:* Healthy ({user_count:,} users)"
    else:
        db_text = ":x: *Database:* No data synced"

    # Last sync line
    if last_sync:
        sync_text = f"*Last sync:* {last_sync}"
    else:
        sync_text = "*Last sync:* Never"

    # Status line
    if active_sync:
        progress = active_sync.get("progress", 0)
        status_text = f"*Status:* Syncing ({progress}%)"
    else:
        status_text = "*Status:* Idle"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{db_text}\n{sync_text}\n{status_text}",
        }
    })

    if not db_healthy and not active_sync:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "Run `/tako sync` to sync your Okta data.",
            }]
        })

    return blocks


def format_sync_progress_message(
    stage: str,
    progress: Optional[int] = None,
) -> str:
    """Return a single-line Slack text string for sync progress updates."""
    if progress is not None:
        return f":arrows_counterclockwise: *Okta Sync* — {stage} ({progress}%)"
    return f":arrows_counterclockwise: *Okta Sync* — {stage}"


def format_sync_complete_message(
    entity_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Format sync completion summary as Slack blocks."""
    users = entity_counts.get("users", 0)
    groups = entity_counts.get("groups", 0)
    apps = entity_counts.get("applications", 0)

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":white_check_mark: *Okta Sync Complete*\n"
                    f"• Users: {users:,}\n"
                    f"• Groups: {groups:,}\n"
                    f"• Applications: {apps:,}"
                ),
            }
        }
    ]


def format_help_message() -> List[Dict[str, Any]]:
    """Format /tako help output as Slack blocks."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":robot_face: *Tako AI — Slack Commands*\n\n"
                    "`/tako <query>` — Ask anything about your Okta data\n"
                    "`/tako sync` — Sync Okta data to the local database\n"
                    "`/tako status` — Check database health & last sync time\n"
                    "`/tako help` — Show this help message\n\n"
                    "_Examples:_\n"
                    "• `/tako list all active users`\n"
                    "• `/tako show groups with more than 50 members`\n"
                    "• `/tako which apps use SAML?`"
                ),
            }
        }
    ]


def results_to_csv_string(results: List[Dict[str, Any]], headers: List[str]) -> str:
    """Convert results to CSV string for file upload."""
    output = io.StringIO()
    if not headers and results:
        headers = list(results[0].keys())
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in results:
        writer.writerow(row)
    return output.getvalue()


# ============================================================================
# Internal helpers
# ============================================================================

def _truncate(text: str, max_length: int) -> str:
    """Truncate text with ellipsis if it exceeds max_length."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _markdown_to_slack(md: str) -> str:
    """
    Minimal conversion from GitHub-flavored markdown to Slack mrkdwn.

    Slack uses its own formatting:
    - Bold: *text* (same)
    - Italic: _text_ (same)
    - Code: `text` (same)
    - Headers: just bold the line
    """
    lines = md.split("\n")
    converted = []
    for line in lines:
        stripped = line.lstrip("#").strip()
        if line.startswith("#"):
            converted.append(f"*{stripped}*")
        else:
            converted.append(line)
    return "\n".join(converted)


def _build_table_text(
    results: List[Dict[str, Any]],
    headers: List[str],
    max_rows: int = 10
) -> str:
    """Build a fixed-width text table for display in Slack code blocks."""
    if not results:
        return ""

    # Determine headers
    if not headers:
        headers = list(results[0].keys())

    # Calculate column widths (cap at 30 chars per column)
    col_widths = {}
    for h in headers:
        col_widths[h] = min(30, max(
            len(str(h)),
            *(len(str(row.get(h, ""))) for row in results[:max_rows])
        ))

    # Build header row
    header_line = " | ".join(str(h).ljust(col_widths[h])[:col_widths[h]] for h in headers)
    separator = "-+-".join("-" * col_widths[h] for h in headers)

    # Build data rows
    data_lines = []
    for row in results[:max_rows]:
        line = " | ".join(
            str(row.get(h, "")).ljust(col_widths[h])[:col_widths[h]]
            for h in headers
        )
        data_lines.append(line)

    return "\n".join([header_line, separator] + data_lines)
