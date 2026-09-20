"""Bounded Adaptive Cards; result data is never executable card markup."""
import json
import re

DISCLAIMER = "AI can make mistakes. Please validate the data provided."
HELP = ("Ask an Okta question, then type below to refine the results or answer a clarification. "
        "Use New Query (or type new) to start fresh. Download CSV saves retrieved rows through Teams' OneDrive consent flow. "
        "Commands: help, status, cancel, new.")
# Teams bot messages support ~100 KB; keep Microsoft's recommended 80 KB budget.
MAX_CARD_BYTES = 80 * 1024
PREVIEW_ROWS = 10


def plain(value, limit=160):
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value if value is not None else "—")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if len(text) > limit:
        text = text[:limit] + "…"
    # Cards support markdown. Prevent data from creating links, mentions or emphasis.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_\[\]()!#])", r"\\\1", text)


def text_block(text, **kwargs):
    return {"type": "TextBlock", "text": text, "wrap": True, **kwargs}


def table_preview(rows: list, headers: list) -> dict:
    """Separate display labels from row keys, including web UI header objects."""
    columns = []
    for header in headers[:4]:
        if isinstance(header, dict):
            key = str(header.get("value") or header.get("key") or header.get("text") or header.get("title") or "")
            label = str(header.get("text") or header.get("title") or key)
        else:
            label = key = str(header)
        columns.append((label, key))
    cells = [[plain(label, 40) for label, _ in columns]]
    for row in rows[:PREVIEW_ROWS]:
        cells.append([
            plain(row.get(key) if isinstance(row, dict)
                  else row[index] if isinstance(row, list) and index < len(row) else None, 96)
            for index, (_, key) in enumerate(columns)
        ])
    # Older clients can still render aligned columns without Table (schema 1.5).
    fallback = {"type": "Container", "items": [
        {"type": "ColumnSet", "separator": index > 0, "columns": [
            {"type": "Column", "width": "stretch", "items": [
                text_block(value, size="Small", weight="Bolder" if index == 0 else "Default")
            ]} for value in row
        ]} for index, row in enumerate(cells)
    ]}
    return {
        "type": "Table", "requires": {"adaptiveCards": "1.5"}, "fallback": fallback,
        "firstRowAsHeader": True, "showGridLines": True, "gridStyle": "default",
        "columns": [{"width": 1} for _ in columns],
        "rows": [{"type": "TableRow", "cells": [
            {"type": "TableCell", "style": "emphasis" if index == 0 else "default", "items": [
                text_block(value, size="Small", weight="Bolder" if index == 0 else "Default")
            ]} for value in row
        ]} for index, row in enumerate(cells)],
    }


def result_card(query: str, result: dict) -> dict:
    outcome = result.get("outcome", "completed")
    label = {"working": "Working…", "clarify": "Clarification needed", "fail": "Could not complete",
             "degraded_success": "Partial results", "cancelled": "Cancelled", "new_query": "New session started"}.get(outcome, "Completed")
    error_style = {"color": "Attention"} if outcome == "fail" else {}
    body = [text_block(plain(query, 240), weight="Bolder"),
            text_block(label, weight="Bolder", separator=True, spacing="Medium", **error_style)]
    if outcome == "new_query":
        body = [text_block(label, weight="Bolder")]
    if outcome == "degraded_success":
        body.append(text_block("Some requested data could not be retrieved. This answer may be incomplete.", color="Warning"))
    rows = result.get("results", result.get("data", []))
    if result.get("display_type") == "table" and isinstance(rows, list):
        headers = result.get("headers") or (list(rows[0]) if rows and isinstance(rows[0], dict) else [])
        if not headers and rows and isinstance(rows[0], list):
            headers = [f"Column {index + 1}" for index in range(len(rows[0]))]
        body.append(text_block(f"{len(rows):,} records retrieved · showing {min(PREVIEW_ROWS, len(rows))}"))
        if rows and headers:
            body.append(table_preview(rows, headers))
        if len(headers) > 4 or len(rows) > PREVIEW_ROWS:
            body.append(text_block(f"Preview only: {min(PREVIEW_ROWS, len(rows))} of {len(rows):,} retrieved rows and {min(4, len(headers))} of {len(headers)} columns. Ask a narrower question to see more."))
        if rows:
            body.append(text_block("Long values are shortened in this preview.", size="Small", isSubtle=True))
        if not rows:
            body.append(text_block("No matching records found."))
    elif outcome != "working":
        body.append(text_block(plain(result.get("content", "No matching records found."), 5000), **error_style))
    if outcome == "clarify":
        body.append(text_block("Reply below with the missing details to continue this question."))
    reference = result.get("result_reference")
    if reference:
        body.append(text_block("Want to refine these results or ask a follow-up question? Just type below.", size="Small"))
    body.append(text_block(DISCLAIMER, size="Small", isSubtle=True))
    card = {"type": "AdaptiveCard", "version": "1.2", "body": body}
    if reference:
        card["actions"] = [{"type": "Action.Submit", "title": "New Query", "data": {"tako_action": "new_query"}}]
        if result.get("display_type") == "table" and rows:
            card["actions"].append({"type": "Action.Submit", "title": "Download CSV",
                                    "data": {"tako_action": "download", "reference": reference}})
    # Include generous room for the Bot Service envelope. Unicode counts in UTF-16.
    if len(json.dumps(card, ensure_ascii=False).encode("utf-16-le")) > MAX_CARD_BYTES - 2048:
        card["body"] = [body[0], body[1], text_block("The preview is too large. Please narrow your question."), body[-1]]
    return card
