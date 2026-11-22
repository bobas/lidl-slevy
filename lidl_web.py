#!/usr/bin/env python3
"""Start the local web interface from a checkout without installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lidl_watch.web import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
