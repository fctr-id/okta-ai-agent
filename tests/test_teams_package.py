"""The distributable package folder must work without Tako or installed packages."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

SOURCE = Path(__file__).resolve().parents[1] / "src" / "integrations" / "teams" / "app_package"
CLIENT = "11111111-1111-1111-1111-111111111111"


class StandalonePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "Standalone Teams folder"
        self.folder.mkdir()
        for name in ("build.py", "manifest.template.json", "color.png", "outline.png"):
            shutil.copy2(SOURCE / name, self.folder / name)

    def run_builder(self, *args, input=""):
        # Isolated mode without site-packages: proves no dependency on the repository or venv.
        return subprocess.run([sys.executable, "-I", "-S", str(self.folder / "build.py"), *args],
                              cwd=self.root, input=input, capture_output=True, text=True, timeout=10)

    def test_prompt_retries_invalid_id_and_prints_upload_path(self):
        run = self.run_builder(input=f"not-an-id\n{CLIENT}\n")
        self.assertEqual(run.returncode, 0, run.stderr)
        output = self.folder / "output" / f"Tako-AI-Teams-{CLIENT}.zip"
        self.assertIn(str(output.resolve()), run.stdout)
        self.assertIn("Upload a custom app", run.stdout)
        with ZipFile(output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), {"manifest.json", "color.png", "outline.png"})
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["bots"][0]["botId"], CLIENT)
            self.assertEqual(manifest["developer"]["termsOfUseUrl"], "https://github.com/fctr-id/okta-ai-agent/blob/main/LICENSE")

    def test_flags_override_urls_and_output_without_prompt(self):
        output = self.root / "custom output" / "app.zip"
        run = self.run_builder("--client-id", CLIENT, "--output", str(output),
                               "--privacy", "https://example.test/privacy")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("Entra Application (client) ID:", run.stdout)
        with ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["developer"]["privacyUrl"], "https://example.test/privacy")
        second = self.run_builder("--bot-id", CLIENT, "--output", str(output))
        self.assertEqual(second.returncode, 0, second.stderr)
        with ZipFile(output) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["id"], manifest["id"])

    def test_invalid_or_missing_input_creates_no_package(self):
        for args in (("--client-id", "bad"), ("--client-id", "00000000-0000-0000-0000-000000000000"), ()):
            run = self.run_builder(*args)
            self.assertEqual(run.returncode, 2)
            self.assertFalse((self.folder / "output").exists())

    def test_missing_icon_does_not_replace_previous_package(self):
        output = self.root / "existing.zip"
        output.write_bytes(b"existing package")
        (self.folder / "outline.png").unlink()
        run = self.run_builder("--client-id", CLIENT, "--output", str(output))
        self.assertEqual(run.returncode, 2)
        self.assertEqual(output.read_bytes(), b"existing package")


if __name__ == "__main__":
    unittest.main()
