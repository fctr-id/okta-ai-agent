# File: run.py (in project root)
import os
import sys
from pathlib import Path

src_path = Path(__file__).parent / "src"
sys.path.append(str(src_path))

# Import and run the sync script
from okta_db_sync.fetch_okta_data import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())