"""Load the project's environment before any settings are captured."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


@lru_cache(maxsize=1)
def load_environment() -> None:
    # Preserve the application's existing file-over-environment precedence,
    # but apply it before Settings is created, regardless of import order.
    load_dotenv(ENV_FILE, override=True, encoding="utf-8")
