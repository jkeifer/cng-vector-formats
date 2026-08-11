"""The namespace the src/ template generators run in (see [tool.render]).

Everything at module level here is visible to the cog generators embedded in
src/. Rendering always targets the *recorded* location: set_location.py
records the new slug first, then re-renders, so this needs no arguments.
"""

from common import REPO_ROOT

# "Unused" imports here are part of the generator namespace: the byte-count
# generators in src/ call utf8_len even though nothing in this file does.
from location import recorded, utf8_len  # noqa: F401

loc = recorded(REPO_ROOT)
