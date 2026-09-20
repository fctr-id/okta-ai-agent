import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.integrations.teams.retention import remove_expired_sessions


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cutoff = time.time() - 86400

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, *, name=None, run_id=None):
        directory = self.root / "sessions" / (name or f"teams-{'a' * 32}-{uuid4()}")
        result = directory / "turns" / f"0001-{run_id or uuid4()}" / "results" / "data.json"
        result.parent.mkdir(parents=True)
        result.write_text("[]", encoding="utf-8")
        for path in [*directory.rglob("*"), directory]:
            os.utime(path, (self.cutoff - 60, self.cutoff - 60))
        return directory, result

    def test_removes_expired_complete_folder_but_keeps_web_and_active_runs(self):
        old, _ = self.session()
        web, _ = self.session(name=f"web-user-{uuid4()}")
        run_id = str(uuid4())
        active, _ = self.session(run_id=run_id)
        self.assertEqual(remove_expired_sessions(self.root, cutoff=self.cutoff, active_run_ids={run_id}), 1)
        self.assertFalse(old.exists())
        self.assertTrue(web.exists())
        self.assertTrue(active.exists())

    def test_recent_activity_in_old_session_extends_retention(self):
        directory, result = self.session()
        os.utime(result, None)
        self.assertEqual(remove_expired_sessions(self.root, cutoff=self.cutoff, active_run_ids=set()), 0)
        self.assertTrue(directory.exists())

    def test_reparse_point_inside_session_prevents_deletion(self):
        directory, result = self.session()
        from src.integrations import session_retention as retention
        original = retention._is_link
        with patch.object(retention, "_is_link", side_effect=lambda path: path == result or original(path)):
            self.assertEqual(remove_expired_sessions(self.root, cutoff=self.cutoff, active_run_ids=set()), 0)
        self.assertTrue(result.exists())

    def test_resolved_target_cannot_escape_configured_root(self):
        directory, _ = self.session()
        outside = self.root / "outside"
        outside.mkdir()
        keep = outside / "keep.txt"
        keep.write_text("keep", encoding="utf-8")
        original = Path.resolve
        with patch.object(Path, "resolve", lambda path, *args, **kwargs: outside if path == directory else original(path, *args, **kwargs)):
            self.assertEqual(remove_expired_sessions(self.root, cutoff=self.cutoff, active_run_ids=set()), 0)
        self.assertTrue(keep.exists())
        self.assertTrue(directory.exists())

    def test_missing_root_is_noop(self):
        self.assertEqual(remove_expired_sessions(self.root / "missing", cutoff=self.cutoff, active_run_ids=set()), 0)
