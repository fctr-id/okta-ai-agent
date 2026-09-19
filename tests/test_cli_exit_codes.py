"""Exercise the real CLI entry point offline, with mocked application boundaries."""
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


CLI = Path(__file__).resolve().parents[1] / "scripts" / "tako-cli.py"


def run_fixture(scenario):
    """No real configuration, model, or Okta client is loaded in this process."""
    def module(name, **members):
        fixture = ModuleType(name)
        fixture.__dict__.update(members)
        sys.modules[name] = fixture

    with TemporaryDirectory() as directory:
        root = Path(directory)
        paths = SimpleNamespace(artifacts_file=root / "artifacts.json", results_dir=root / "results")

        async def orchestrate(**kwargs):
            current = "timeout" if kwargs["user_query"] == "fail" else scenario
            globals_ = kwargs["event_callback"].__globals__
            globals_["project_root"] = root
            payload = {"data": [{"value": "fixture"}], "count": 1, "display_type": "table"}
            if current == "script_failure":
                payload = None
            elif current == "empty_table":
                payload = {"data": [], "count": 0, "display_type": "table"}
            elif current == "markdown":
                payload = {"content": "Fixture answer", "display_type": "markdown"}
            globals_["execute_generated_script"] = AsyncMock(return_value=payload)
            if current == "analysis":
                globals_["execute_generated_script"].side_effect = AssertionError("Completed analysis must not execute a retrieval script")
            if current == "csv_failure":
                globals_["save_results_to_csv"] = Mock(return_value=None)
            if current == "exception":
                raise RuntimeError("Fixture unexpected failure")
            return SimpleNamespace(
                success=current != "timeout", error="Request timed out.",
                no_data_found=current == "empty", user_message="No fixture matches" if current == "empty" else None,
                completed_result=payload if current == "analysis" else None,
                completed_result_event=lambda: {**payload, "results": payload["data"]},
                is_degraded_success=False, is_special_tool=current == "special",
                script_code="" if current in {"missing_script", "analysis"} else "print('fixture')",
                display_type="markdown" if current == "special" else "table",
                outcome_metadata=lambda: {"outcome": "success"},
                total_input_tokens=0, total_output_tokens=0, total_tokens=0, total_requests=0,
            )

        module("dotenv", load_dotenv=Mock())
        module("src.config.settings", settings=SimpleNamespace())
        module("src.core.agents.orchestrator", execute_multi_agent_query=orchestrate)
        module("src.core.okta.client", OktaClient=Mock())
        module("src.data.schemas.runtime_storage",
               create_runtime_turn_paths=Mock(return_value=paths),
               prepare_runtime_script_code=lambda code: code,
               update_turn_metadata=Mock(), write_turn_summary=Mock())
        module("src.utils.logging", get_logger=Mock(return_value=Mock()),
               set_correlation_id=Mock(), generate_correlation_id=Mock(return_value="fixture-run"))
        sys.argv = [str(CLI), "fixture query"]
        if scenario == "script_only":
            sys.argv.append("--scriptonly")
        elif scenario == "interactive":
            sys.argv = [str(CLI), "--interactive"]
        runpy.run_path(str(CLI), run_name="__main__")


class CLIExitCodeTests(unittest.TestCase):
    def run_cli(self, scenario, stdin=None):
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--fixture", scenario],
            input=stdin, capture_output=True, text=True, timeout=20,
        )

    def test_synthesis_timeout_exits_nonzero(self):
        result = self.run_cli("timeout")
        self.assertIn("Request timed out.", result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_missing_script_and_execution_failure_exit_nonzero(self):
        for scenario in ("missing_script", "script_failure", "csv_failure"):
            with self.subTest(scenario=scenario):
                result = self.run_cli(scenario)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_successful_outputs_and_empty_results_exit_zero(self):
        for scenario in ("table", "empty", "empty_table", "special", "markdown", "script_only", "analysis"):
            with self.subTest(scenario=scenario):
                result = self.run_cli(scenario)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unexpected_exception_exits_nonzero(self):
        result = self.run_cli("exception")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Fixture unexpected failure", result.stderr)

    def test_interactive_continues_after_failure_and_preserves_failure_exit(self):
        result = self.run_cli("interactive", "fail\nnext query\nquit\n")
        self.assertIn("Request timed out.", result.stdout)
        self.assertIn("Execution complete!", result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_successful_interactive_session_exits_zero(self):
        result = self.run_cli("interactive", "next query\nquit\n")
        self.assertIn("Execution complete!", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        run_fixture(sys.argv[2])
    else:
        unittest.main()
