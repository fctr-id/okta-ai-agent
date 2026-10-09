"""Synthetic snapshot checks for the trusted directory-only SQL connection."""
from tests.security_support import CHECKS
import sqlite3
import unittest
from unittest.mock import patch

from src.config.settings import settings
from src.core.okta.client.read_database import open_database


class ReadDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.path = CHECKS / f'{self._testMethodName}.db'
        with sqlite3.connect(self.path) as connection:
            connection.executescript('''CREATE TABLE users (okta_id TEXT, profile TEXT);
                INSERT INTO users VALUES ('fixture', '{"city":"Boston"}');
                CREATE TABLE auth_users (username TEXT);
                CREATE TABLE query_procedures (script_code TEXT);''')
        setting = patch.object(settings, 'SQLITE_PATH', str(self.path))
        setting.start()
        self.addCleanup(setting.stop)

    def test_reads_ctes_aggregates_and_json_preserve_rows(self):
        connection = open_database()
        try:
            row = connection.execute('WITH scoped AS (SELECT * FROM users) SELECT okta_id, json_extract(profile, \'$.city\') AS city FROM scoped').fetchone()
            self.assertEqual(dict(row), {'okta_id': 'fixture', 'city': 'Boston'})
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
        finally:
            connection.close()

    def test_internal_tables_and_mutations_are_denied(self):
        connection = open_database()
        try:
            for query in ('SELECT * FROM auth_users', 'SELECT * FROM query_procedures',
                          "UPDATE users SET okta_id = 'changed'", 'PRAGMA table_info(users)'):
                with self.subTest(query=query), self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(query)
            self.assertEqual(connection.execute('SELECT okta_id FROM users').fetchone()[0], 'fixture')
        finally:
            connection.close()

    def test_missing_snapshot_is_not_created(self):
        path = CHECKS / 'missing.db'
        with patch.object(settings, 'SQLITE_PATH', str(path)), self.assertRaises(ValueError):
            open_database()
        self.assertFalse(path.exists())
