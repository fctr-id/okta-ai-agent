"""Explicit synthetic configuration for offline security compatibility tests."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import atexit

ROOT = Path(__file__).resolve().parents[1]
_temporary = TemporaryDirectory(prefix='tako-security-tests-')
atexit.register(_temporary.cleanup)
CHECKS = Path(_temporary.name)
os.environ.update({
    'PYTHON_DOTENV_DISABLED': '1',
    'TAKO_ENV_FILE': str(CHECKS / 'no-configuration-file'),
    'DB_DIR': str(CHECKS / 'database'),
    'DB_FILENAME': 'offline.db',
    'CHAT_SESSIONS_DIR': str(CHECKS / 'conversations'),
    'OKTA_CLIENT_ORGURL': 'https://offline.okta.invalid',
    'OKTA_API_TOKEN': 'offline-check-only',
    'OKTA_AUTH_METHOD': 'api_token',
    'JWT_SECRET_KEY': 'offline-test-signing-key-with-at-least-32-bytes',
    'TEAMS_ENABLE': 'false', 'ENABLE_SLACK_BOT': 'false',
    'QUERY_PROCEDURES_ENABLED': 'false',
    'AI_PROVIDER': 'openai_compatible', 'OPENAI_COMPATIBLE_TOKEN': 'offline-check-only',
    'OPENAI_COMPATIBLE_BASE_URL': 'https://models.invalid/v1',
    'OPENAI_COMPATIBLE_REASONING_MODEL': 'offline', 'OPENAI_COMPATIBLE_CODING_MODEL': 'offline',
})
