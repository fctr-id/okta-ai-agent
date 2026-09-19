"""
Agents package for Tako v1.0.0-beta
Contains core AI agents for the Okta AI Agent system
"""

import os
from pathlib import Path
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings, ThinkingLevel

from src.core.models.model_picker import ModelConfig, ModelType


DEFAULT_AGENT_KWARGS: dict[str, Any] = {
	"retries": 0,
	"output_retries": 1,
}

# Shared default for fast local tools only.
# Long-running remote or generated-execution tools should opt into their own budget or no hard timeout.
DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS = 20.0

DEFAULT_AGENT_METADATA: dict[str, str] = {
	"framework": "pydantic_ai",
	"implementation_phase": "phase1",
}

USER_MESSAGE_INSTRUCTIONS = (Path(__file__).parent / "prompts" / "user_messages.txt").read_text(encoding="utf-8")


def get_default_model_settings() -> ModelSettings:
	"""Read optional shared reasoning effort; leave model defaults intact when unset."""
	effort = os.getenv("AI_REASONING_EFFORT", "").strip().lower()
	if effort in {"", "none"}:
		return ModelSettings()
	if effort in {"true", "false"}:
		return ModelSettings(thinking=effort == "true")
	if effort not in {"minimal", "low", "medium", "high", "xhigh"}:
		raise ValueError("AI_REASONING_EFFORT must be minimal, low, medium, high, xhigh, true, false, or none (or unset/blank)")
	return ModelSettings(thinking=cast(ThinkingLevel, effort))


def build_agent(model_type: ModelType, /, *, name: str, **agent_kwargs: Any) -> Agent[Any, Any]:
	"""Create an agent with shared Phase 1 defaults while keeping model selection centralized."""
	model = ModelConfig.get_model(model_type)
	model_settings = get_default_model_settings()
	model_settings.update(agent_kwargs.pop("model_settings", None) or {})
	instructions = agent_kwargs.pop("instructions", ()) or ()
	if isinstance(instructions, str) or callable(instructions):
		instructions = (instructions,)
	provided_metadata = agent_kwargs.pop("metadata", None)
	combined_metadata = {
		**DEFAULT_AGENT_METADATA,
		"agent_name": name,
		"model_type": model_type.value,
	}
	if isinstance(provided_metadata, dict):
		combined_metadata.update(provided_metadata)
	elif provided_metadata is not None:
		combined_metadata = provided_metadata

	combined_kwargs = {
		**DEFAULT_AGENT_KWARGS,
		**agent_kwargs,
		"name": name,
		"metadata": combined_metadata,
		"model_settings": model_settings,
		"instructions": (*instructions, USER_MESSAGE_INSTRUCTIONS),
	}
	return Agent(model, **combined_kwargs)

__all__ = [
	"DEFAULT_AGENT_KWARGS",
	"DEFAULT_AGENT_METADATA",
	"DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS",
	"build_agent",
	"get_default_model_settings",
]
