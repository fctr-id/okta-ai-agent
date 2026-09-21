"""Advisory synthesis metadata; never an authorization or execution decision."""
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ProcedureMetadata(BaseModel):
    purpose: str = Field(min_length=1, max_length=600, description="Concise description of the retrieval, without result rows or counts.")
    entities: list[str] = Field(max_length=20, description="Canonical entity names from the supplied catalog.")
    scope: str = Field(min_length=1, max_length=600, description="Population, filters, relationships, freshness and exclusions; do not include personal identifier values.")
    parameters: list[str] = Field(max_length=20, description="Names of query-specific inputs, never their values.")
    classification: Literal['generic', 'parameterized', 'conversation_dependent']
    contains_sensitive_literals: bool = Field(description="Whether question, context or retrieval uses a specific person's identifiers or other private literals. Requesting email columns alone is not a personal literal.")


@lru_cache(maxsize=1)
def entity_catalog() -> frozenset[str]:
    path = Path(__file__).with_name('Okta_API_entitity_endpoint_reference_GET_ONLY.json')
    return frozenset(json.loads(path.read_text(encoding='utf-8'))['entity_summary'])


def executed_fields(event: dict) -> list[str]:
    """Use actual row keys, or declared output headers for a valid empty table."""
    rows = event.get('data', event.get('results', []))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Expected flat result rows')
    if rows:
        return list(dict.fromkeys(key for row in rows for key in row))
    keys = [header.get('value', header.get('key')) if isinstance(header, dict) else header
            for header in event.get('headers', [])]
    return list(dict.fromkeys(key for key in keys if isinstance(key, str) and key))
