"""Keep spreadsheet formula-like strings literal without changing numeric data."""


def csv_literal(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value
