"""Offline contracts for shared reasoning settings and agent overrides."""
import os
import unittest
from unittest.mock import patch

from pydantic_ai.models.test import TestModel

from src.core.agents import build_agent, get_default_model_settings
from src.core.models.model_picker import ModelConfig, ModelType


class AgentSettingsTests(unittest.TestCase):
    def test_missing_blank_or_none_omits_thinking(self):
        for value in (None, "", "  ", "none", " NONE "):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("AI_REASONING_EFFORT", None)
                else:
                    os.environ["AI_REASONING_EFFORT"] = value
                self.assertEqual(get_default_model_settings(), {})
                with patch.object(ModelConfig, "get_model", return_value=TestModel()):
                    agent = build_agent(ModelType.REASONING, name="unset",
                                        model_settings={"temperature": 0.2})
                    self.assertEqual(agent.model_settings, {"temperature": 0.2})

    def test_effort_values_and_booleans(self):
        values = {level: level for level in ("minimal", "low", "medium", "high", "xhigh")}
        values.update({" TRUE ": True, "false": False, " HIGH ": "high"})
        for value, expected in values.items():
            with self.subTest(value=value), patch.dict(os.environ, AI_REASONING_EFFORT=value):
                self.assertEqual(get_default_model_settings(), {"thinking": expected})

    def test_invalid_effort_has_clear_error(self):
        with patch.dict(os.environ, AI_REASONING_EFFORT="typo"):
            with self.assertRaisesRegex(ValueError, "AI_REASONING_EFFORT must be"):
                get_default_model_settings()

    def test_agent_merges_settings_without_losing_explicit_overrides(self):
        with patch.dict(os.environ, AI_REASONING_EFFORT="high"), \
             patch.object(ModelConfig, "get_model", return_value=TestModel()):
            default_agent = build_agent(ModelType.REASONING, name="default")
            self.assertEqual(default_agent.model_settings, {"thinking": "high"})
            settings = {"temperature": 0.2, "thinking": False}
            agent = build_agent(ModelType.REASONING, name="override", model_settings=settings)
            self.assertEqual(agent.model_settings, settings)
            self.assertEqual(settings, {"temperature": 0.2, "thinking": False})
            agent = build_agent(ModelType.REASONING, name="temperature", model_settings={"temperature": 0.2})
            self.assertEqual(agent.model_settings, {"thinking": "high", "temperature": 0.2})


if __name__ == "__main__":
    unittest.main()
