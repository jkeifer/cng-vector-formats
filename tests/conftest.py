"""Put scripts/ on sys.path so the tests can import the scripts as modules.

This project is not a package (`[tool.uv] package = false`), so there is no
installed distribution to import from.
"""

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
