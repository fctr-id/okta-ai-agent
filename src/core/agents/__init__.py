"""
Agents package for Tako v1.0.0-beta
Contains core AI agents for the Okta AI Agent system
"""

from typing import Any

from pydantic_ai import Agent

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


def build_agent(model_type: ModelType, /, *, name: str, **agent_kwargs: Any) -> Agent[Any, Any]:
	"""Create an agent with shared Phase 1 defaults while keeping model selection centralized."""
	model = ModelConfig.get_model(model_type)
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
	}
	return Agent(model, **combined_kwargs)

__all__ = [
	"DEFAULT_AGENT_KWARGS",
	"DEFAULT_AGENT_METADATA",
	"DEFAULT_LOCAL_TOOL_CALL_TIMEOUT_SECONDS",
	"build_agent",
]
