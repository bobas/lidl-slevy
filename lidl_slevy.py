#!/usr/bin/env python3
"""Run directly from a checkout without installing dependencies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lidl_watch.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
