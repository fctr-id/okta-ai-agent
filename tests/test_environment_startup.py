"""Check startup precedence in isolation, without loading real credentials."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnvironmentStartupTests(unittest.TestCase):
    def check_startup(self, logging_first, with_file=True):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Copy only source modules. Never import the real app configuration.
            for relative in (
                "src/config/environment.py",
                "src/config/settings.py",
                "src/utils/logging.py",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)

            if with_file:
                (root / ".env").write_text(
                    "OKTA_API_TOKEN=file-fixture\n"
                    "OKTA_CLIENT_ORGURL=https://file-fixture.okta.com\n",
                    encoding="utf-8",
                )
            working = root / "different-working-directory"
            working.mkdir()
            (working / ".env").write_text(
                "OKTA_API_TOKEN=wrong-directory-fixture\n", encoding="utf-8"
            )
            env = {
                key: os.environ[key]
                for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                if key in os.environ
            }
            env.update(
                PYTHONPATH=str(root),
                OKTA_API_TOKEN="inherited-fixture",
                OKTA_CLIENT_ORGURL="https://inherited-fixture.okta.com",
                LOG_LEVEL="ERROR",
            )
            first, second = (
                ("src.utils.logging", "src.config.settings")
                if logging_first
                else ("src.config.settings", "src.utils.logging")
            )
            expected = "file-fixture" if with_file else "inherited-fixture"
            code = f"""
import os
import {first}
import {second}
from src.config.settings import settings
from src.config.environment import load_environment
assert settings.OKTA_API_TOKEN == os.environ['OKTA_API_TOKEN'] == {expected!r}
assert settings.OKTA_CLIENT_ORGURL == os.environ['OKTA_CLIENT_ORGURL'] == 'https://{expected}.okta.com'
# Subsequent imports/calls must not reset deliberate runtime overrides.
os.environ['OKTA_API_TOKEN'] = 'runtime-fixture'
load_environment()
assert os.environ['OKTA_API_TOKEN'] == 'runtime-fixture'
"""
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=working, env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_settings_before_logging(self):
        self.check_startup(logging_first=False)

    def test_logging_before_settings(self):
        self.check_startup(logging_first=True)

    def test_environment_only_deployment(self):
        self.check_startup(logging_first=False, with_file=False)


if __name__ == "__main__":
    unittest.main()
