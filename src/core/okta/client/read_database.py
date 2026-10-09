"""Read-only access to the configured directory snapshot for generated scripts."""
import sqlite3
from pathlib import Path


def open_database():
    from src.config.settings import settings
    path = Path(settings.SQLITE_PATH).resolve()
    if not path.is_file():
        raise ValueError('Run Sync now before querying the local directory snapshot')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    allowed = {'users', 'groups', 'applications', 'policies', 'authenticators',
               'user_factors', 'devices', 'user_devices', 'user_group_memberships',
               'user_application_assignments', 'group_application_assignments'}
    def authorize(action, arg1, arg2, database, source):
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if arg1 in allowed else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == 'load_extension':
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE} else sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)
    return connection
