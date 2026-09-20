"""JWT key lifecycle and forgery regression tests using isolated fixture config."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS"


class JwtSecretTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Copy source only; never load the developer's environment file.
        for relative in ("src/config/environment.py", "src/config/settings.py",
                         "src/utils/logging.py", "src/core/security/jwt.py"):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
                    if key in os.environ}
        self.env.update(PYTHONPATH=str(self.root), OKTA_API_TOKEN="fixture-only",
                        OKTA_CLIENT_ORGURL="https://fixture.okta.com", LOG_LEVEL="ERROR")

    def run_fixture(self, code, key=None, success=True):
        env = dict(self.env)
        if key is not None:
            env["JWT_SECRET_KEY"] = key
        result = subprocess.run([sys.executable, "-c", code], cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_public_default_signed_token_is_rejected(self):
        self.run_fixture('''
from datetime import datetime, timedelta, timezone
from jose import jwt
from src.core.security.jwt import decode_access_token, create_access_token
now = datetime.now(timezone.utc)
payload = {'sub': 'fixture-admin', 'role': 'admin', 'type': 'access',
           'iat': now, 'nbf': now, 'exp': now + timedelta(minutes=10),
           'iss': 'fctr-okta-ai-agent', 'aud': 'ui-user'}
for public_key in ('CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS', 'default_secret_insecure'):
    forged = jwt.encode(payload, public_key, algorithm='HS256')
    assert decode_access_token(forged) is None, 'Public default key authenticated a forged token'
assert decode_access_token(create_access_token({'sub': 'fixture-admin'}))['sub'] == 'fixture-admin'
''', key=PLACEHOLDER)

    def test_missing_blank_and_placeholder_keys_get_one_process_key(self):
        for key in (None, '', '   ', PLACEHOLDER, f' {PLACEHOLDER.lower()} ',
                    'default_secret_insecure'):
            with self.subTest(configured=key):
                self.run_fixture('''
import os
from src.config.settings import Settings, settings
key = settings.JWT_SECRET_KEY
assert len(key) >= 64
assert key not in ('CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS', 'default_secret_insecure')
assert Settings().JWT_SECRET_KEY == key
assert key not in repr(settings)
assert os.environ.get('JWT_SECRET_KEY') != key
''', key=key)

    def test_restart_invalidates_login_but_preserves_stored_data(self):
        for directory in ('sqlite_db', 'chat_sessions'):
            target = self.root / directory
            target.mkdir()
            (target / 'saved-fixture').write_text('keep this data', encoding='utf-8')
        self.run_fixture('''
from pathlib import Path
from src.core.security.jwt import create_access_token, decode_access_token
token = create_access_token({'sub': 'fixture-user'})
assert decode_access_token(token)['sub'] == 'fixture-user'
Path('session-fixture').write_text(token)
''')
        self.run_fixture('''
from pathlib import Path
from src.core.security.jwt import create_access_token, decode_access_token
assert decode_access_token(Path('session-fixture').read_text()) is None
assert decode_access_token(create_access_token({'sub': 'fixture-user'}))['sub'] == 'fixture-user'
''')
        for directory in ('sqlite_db', 'chat_sessions'):
            self.assertEqual((self.root / directory / 'saved-fixture').read_text(), 'keep this data')
        self.assertFalse((self.root / '.env').exists())

    def test_explicit_key_preserves_login_across_processes_and_rotation_revokes_it(self):
        key = 'fixture-configured-key-' * 4
        self.run_fixture('''
import os
from pathlib import Path
from src.config.settings import settings
from src.core.security.jwt import create_access_token
assert settings.JWT_SECRET_KEY == os.environ['JWT_SECRET_KEY']
Path('session-fixture').write_text(create_access_token({'sub': 'fixture-user'}))
''', key=key)
        self.run_fixture('''
from pathlib import Path
from src.core.security.jwt import decode_access_token
assert decode_access_token(Path('session-fixture').read_text())['sub'] == 'fixture-user'
''', key=key)
        self.run_fixture('''
from pathlib import Path
from src.core.security.jwt import create_access_token, decode_access_token
assert decode_access_token(Path('session-fixture').read_text()) is None
assert decode_access_token(create_access_token({'sub': 'fixture-user'}))['sub'] == 'fixture-user'
''', key='fixture-rotated-key-' * 4)

    def test_short_configured_key_fails_without_disclosing_value(self):
        key = 'short-private-fixture'
        result = self.run_fixture('from src.config.settings import settings', key=key, success=False)
        self.assertIn('JWT_SECRET_KEY', result.stderr)
        self.assertNotIn(key, result.stdout + result.stderr)

    def test_fixture_environment_file_uses_same_key_rules_and_precedence(self):
        # This file is synthetic and exists only in the isolated temporary tree.
        fixture_file = self.root / '.env'
        fixture_file.write_text(f'JWT_SECRET_KEY={PLACEHOLDER}\n', encoding='utf-8')
        self.run_fixture('''
from src.config.settings import settings, Settings
assert settings.JWT_SECRET_KEY != 'CHANGE-THIS-KEY-IN-PRODUCTION-ENVIRONMENTS'
assert settings.JWT_SECRET_KEY != 'inherited-fixture-key-' * 4
assert settings.JWT_SECRET_KEY == Settings().JWT_SECRET_KEY
''', key='inherited-fixture-key-' * 4)
        fixture_file.write_text('JWT_SECRET_KEY=file-fixture-key-file-fixture-key\n', encoding='utf-8')
        self.run_fixture('''
from src.config.settings import settings
assert settings.JWT_SECRET_KEY == 'file-fixture-key-file-fixture-key'
''', key='inherited-fixture-key-' * 4)

    def test_legacy_secret_fallback_cannot_authenticate(self):
        self.run_fixture('''
from types import SimpleNamespace
from jose import jwt
from src.core.security import jwt as session_jwt
session_jwt.settings = SimpleNamespace(SECRET_KEY='legacy-fixture-key-' * 4)
try:
    session_jwt.create_access_token({'sub': 'fixture-user'})
except AttributeError:
    pass
else:
    raise AssertionError('Signing must not fall back to SECRET_KEY')
token = jwt.encode({'sub': 'fixture-user', 'type': 'access',
                    'iss': 'fctr-okta-ai-agent', 'aud': 'ui-user'},
                   session_jwt.settings.SECRET_KEY, algorithm='HS256')
assert session_jwt.decode_access_token(token) is None
''')


if __name__ == '__main__':
    unittest.main()
