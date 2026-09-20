"""Persist final results for transport downloads and shared agent follow-ups."""
import json
from src.data.schemas.artifact_manifest import append_artifacts_with_result_sets


def save_result(paths, event_data, *, filename="response.json"):
    """Save the exact displayed payload and register it for existing follow-up tools."""
    target = paths.results_dir / filename
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(event_data, default=str), encoding="utf-8")
    temporary.replace(target)
    markdown = event_data.get("display_type") == "markdown"
    payload = {
        "key": "turn_output_final", "category": "turn_output",
        "display_type": event_data.get("display_type", "table"),
        "canonical_turn_output": True,
        "content": str(event_data.get("content") or "") if markdown else json.dumps(event_data, default=str),
        "row_count": event_data.get("count"),
        "metadata": event_data.get("metadata") or {},
    }
    artifacts, refs = append_artifacts_with_result_sets(paths.artifacts_file, [payload], source_specialist="unknown")
    if not markdown and refs:
        for artifact in reversed(artifacts):
            if artifact.get("key") == "turn_output_final":
                artifact["content"] = json.dumps({
                    "display_type": event_data.get("display_type", "table"),
                    "headers": event_data.get("headers", []), "count": event_data.get("count", 0),
                    "result_set_refs": [ref.result_set_id for ref in refs], "content_omitted": True,
                })
                artifact["content_omitted"] = True
                break
        paths.artifacts_file.write_text(json.dumps(artifacts, default=str), encoding="utf-8")
