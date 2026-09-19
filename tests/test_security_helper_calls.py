"""Local helper names must not bypass validation of what their bodies do."""
import unittest

from src.utils.security_config import validate_generated_code


class SecurityHelperCallTests(unittest.TestCase):
    def test_declared_helpers_with_sensitive_substrings_are_allowed(self):
        for name in ('execute_query', 'evaluate_status', 'compile_rows', 'normalize_input', 'open_records', 'safe_exec'):
            with self.subTest(name=name):
                result = validate_generated_code(f'def {name}():\n    return []\n{name}()')
                self.assertTrue(result.is_valid, result.violations)

    def test_async_nested_and_forward_helpers_are_allowed(self):
        code = '''async def main():
    def evaluate_rows(rows):
        return [row for row in rows]
    return evaluate_rows(await execute_query())

async def execute_query():
    return []
'''
        result = validate_generated_code(code)
        self.assertTrue(result.is_valid, result.violations)

    def test_unsafe_helper_bodies_remain_blocked(self):
        for body in ('exec("print(1)")', 'eval("1+1")', 'open("private.txt")', 'input()', 'compile("", "", "exec")',
                     'raise SystemExit(1)', 'import subprocess\n    subprocess.run([])'):
            with self.subTest(body=body):
                result = validate_generated_code(f'def execute_query():\n    {body}\nexecute_query()')
                self.assertFalse(result.is_valid)

    def test_undeclared_sensitive_names_are_not_whitelisted(self):
        for code in ('execute_query()', 'client.execute_query()', 'raise SystemExit(1)',
                     'def SystemExit(code):\n    return code\nSystemExit(1)'):
            with self.subTest(code=code):
                self.assertFalse(validate_generated_code(code).is_valid)

    def test_rebinding_or_decorating_does_not_grant_helper_exception(self):
        for code in (
            'def execute_query():\n    return []\nexecute_query = getattr(sys, "exit")\nexecute_query()',
            'def execute_query():\n    return []\nfrom sys import exit as execute_query\nexecute_query()',
            'def execute_query():\n    return []\ndef run(execute_query):\n    execute_query()',
            '@transform\ndef execute_query():\n    return []\nexecute_query()',
        ):
            with self.subTest(code=code):
                self.assertFalse(validate_generated_code(code).is_valid)

    def test_sqlite_helper_uses_existing_allowed_database_calls(self):
        code = '''import sqlite3
def execute_query(connection, query):
    return connection.execute(query).fetchall()
connection = sqlite3.connect(":memory:")
rows = execute_query(connection, "SELECT 1")
connection.close()
'''
        result = validate_generated_code(code)
        self.assertTrue(result.is_valid, result.violations)


if __name__ == '__main__':
    unittest.main()
