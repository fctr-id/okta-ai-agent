"""Exercise console/file logging in isolation without loading application secrets."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LoggingConfigTests(unittest.TestCase):
    def test_agent_trace_reaches_shared_file_once(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "src/utils/logging.py"
            target.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "src/utils/logging.py", target)
            environment = root / "src/config/environment.py"
            environment.parent.mkdir(parents=True)
            environment.write_text("def load_environment(): pass\n", encoding="utf-8")
            working = root / "other-working-directory"
            working.mkdir()
            env = {
                key: os.environ[key]
                for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                if key in os.environ
            }
            env.update(PYTHONPATH=str(root), LOG_LEVEL="INFO", FILE_LOG_LEVEL="DEBUG")
            result = subprocess.run(
                [sys.executable, "-c", '''
from pathlib import Path
from src.utils import logging as log

log.set_correlation_id("trace-fixture")
agent = log.get_logger("okta_ai_agent")
assert log.get_logger("okta_ai_agent") is agent
api = log.get_logger("src.api.fixture")
agent.info("Generated SQL:\\nSELECT okta_id FROM users LIMIT 3")
agent.debug("debug-file-only-fixture")
try:
    raise ValueError("sql-error-fixture")
except ValueError:
    agent.exception("SQL execution failed")
api.info("API fallback fixture")
for handler in agent.handlers + api.handlers:
    handler.flush()
text = (log.get_project_root() / "logs/okta_ai_agent.log").read_text(encoding="utf-8")
for marker in ("Generated SQL:", "SELECT okta_id FROM users LIMIT 3",
               "debug-file-only-fixture", "SQL execution failed", "API fallback fixture"):
    assert text.count(marker) == 1, (marker, text)
assert "ValueError: sql-error-fixture" in text
assert "[trace-fixture] Generated SQL:" in text
assert log._FILE_HANDLER_SINGLETON in agent.handlers
assert log._FILE_HANDLER_SINGLETON in api.handlers
assert log._FILE_HANDLER_SINGLETON in log.logger.handlers
assert not (Path.cwd() / "logs").exists()
log._close_file_handler()
'''],
                cwd=working, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("Generated SQL:"), 1)
            self.assertEqual(result.stdout.count("API fallback fixture"), 1)
            self.assertNotIn("debug-file-only-fixture", result.stdout)


if __name__ == "__main__":
    unittest.main()
