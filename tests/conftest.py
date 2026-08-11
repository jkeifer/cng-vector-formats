"""Put scripts/ on sys.path so the tests can import the location model.

The generic machinery and its tests live in workshopify/; the only code left
here is the repo's own content -- the location model -- and it is not a
package, so the path shim remains.
"""

import sys

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / 'scripts'))
