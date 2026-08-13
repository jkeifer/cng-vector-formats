"""The namespace the src/ template generators run in (see [tool.workshopify]).

Everything at module level here is visible to the cog generators embedded in
src/. workshopify executes this module with `params` (the recorded
[tool.workshopify.params]) and `__file__` pre-bound, and with this directory
on sys.path -- which is what makes the sibling `location` import work.
"""

from pathlib import Path

# "Unused" imports here are part of the generator namespace: the byte-count
# generators in src/ call utf8_len even though nothing in this file does.
from location import load_slug, utf8_len  # noqa: F401

loc = load_slug(
    Path(__file__).resolve().parent.parent / 'locations',
    params['location'],
)

# The screenshot exercise 1 embeds, derived from the recorded location the
# same way the rendered values are: placed on render/set, verified by check.
#
# It sits beside the notebook directories rather than inside one so that a
# single relative reference resolves from both: notebooks/ and
# notebooks-completed/ are at the same depth, so `../notebook-assets/...`
# means the same thing in each.
ASSETS = {'notebook-assets/geojson_io.png': loc.screenshot}
