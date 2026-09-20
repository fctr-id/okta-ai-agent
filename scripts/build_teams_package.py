"""Compatibility entry point; the standalone builder lives in teams-app/."""
from pathlib import Path
from runpy import run_path

_builder = run_path(str(Path(__file__).resolve().parents[1] / "teams-app" / "build.py"))
build_package = _builder["build_package"]
main = _builder["main"]

if __name__ == "__main__":
    raise SystemExit(main())
