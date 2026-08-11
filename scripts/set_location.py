#!/usr/bin/env python3
"""Retarget the workshop to a different building.

Every exercise is built around one building: it is traced in exercise 1,
hand-encoded in exercise 2, and found in Overture in exercise 3. The polygon
appears in three renderings and five prose facts are derived from it, so doing
this by hand is a reliable way to ship stale byte counts.

This performs a verify-then-replace. It renders every substitution site for
both the recorded current location and the target, asserts each current
rendering appears exactly once where it belongs, and only then writes. If any
site is missing or ambiguous, nothing is modified.

    uv run scripts/set_location.py hiroshima
    uv run scripts/set_location.py --check
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib

from dataclasses import dataclass
from pathlib import Path

from location import Location

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_DIR = REPO_ROOT / 'locations'

# The three exercise sources, one per exercise and in exercise order.
SRC_GEOJSON = '01_is-geojson-cloud-native.py'
SRC_WELL_KNOWNS = '02_the-well-knowns.py'
SRC_PARQUET = '03_reading-parquet-the-hard-way.py'

SRC_FILES = (SRC_GEOJSON, SRC_WELL_KNOWNS, SRC_PARQUET)

# Where the active location's screenshot lands. Stable, so the notebook's
# markdown reference never changes.
ACTIVE_SCREENSHOT = Path('notebooks') / 'assets' / 'geojson_io.png'


@dataclass(frozen=True, slots=True)
class Site:
    """One span of text that differs between locations."""

    name: str
    filename: str
    text: str


def sites(loc: Location) -> list[Site]:
    d = loc.derived
    return [
        Site('geojson_str', SRC_GEOJSON, loc.feature_collection),
        Site('geojson_bytes', SRC_GEOJSON, f'{d.geojson_bytes} bytes'),
        Site('sample_pair', SRC_GEOJSON, d.sample_pair),
        Site('sample_pair_bytes', SRC_GEOJSON, f'{d.sample_pair_bytes} bytes'),
        Site('ring_count', SRC_GEOJSON, f'just {d.ring_count}'),
        # Carry the surrounding prose. A bare name is not safe to match on: a
        # feature collection's properties may repeat it (Sacramento's
        # buildingName is "Sheraton Grand Sacramento Hotel"), which would make
        # the name occur twice in the file once geojson_str is substituted.
        Site('city', SRC_GEOJSON, f'all buildings in {loc.city}'),
        Site('region', SRC_GEOJSON, f'Or {loc.region}'),
        Site('macro', SRC_GEOJSON, f'Or all of {loc.macro}'),
        Site('geom_str', SRC_WELL_KNOWNS, loc.geom_str),
        Site('wkt', SRC_WELL_KNOWNS, loc.wkt),
        Site('ring_points', SRC_WELL_KNOWNS, loc.ring_points),
        # Backticked: the bare coordinate also occurs six times inside the
        # geom_str/wkt/ring_points renderings, being the ring's first and last
        # point. Only the prose mention is wrapped in backticks.
        Site('sample_x', SRC_WELL_KNOWNS, f'`{d.sample_x}`'),
        Site('wkt_wkb_ratio', SRC_WELL_KNOWNS, f'{d.wkt_wkb_ratio}x smaller'),
        Site('geom', SRC_PARQUET, loc.geom_pretty),
        # Bare, unlike city/region/macro above, and only safe because of what
        # exercise 3 embeds: `Location.geom_pretty` renders the geometry alone,
        # with no `properties`, so the collection's own buildingName is not in
        # this file to collide with. Anything that put the properties back --
        # or a second prose mention of the building -- breaks that, and
        # `verify()` will say so rather than silently mis-substituting.
        Site('building_name', SRC_PARQUET, loc.building_name),
    ]


def read_sources(repo: Path) -> dict[str, str]:
    """The current text of every source file, keyed by filename."""
    return {name: (repo / 'src' / name).read_text() for name in SRC_FILES}


def verify_sites(texts: dict[str, str], loc: Location) -> list[str]:
    """Errors describing any site not present exactly once in `texts`.

    Takes the text rather than reading it, so a retarget can check what it is
    about to write while it is still only in memory.
    """
    errors: list[str] = []
    for site in sites(loc):
        found = texts[site.filename].count(site.text)
        if found != 1:
            errors.append(
                f'{site.filename}: expected exactly 1 occurrence of site '
                f'{site.name!r}, found {found}',
            )
    return errors


def verify_screenshot(repo: Path, loc: Location) -> list[str]:
    """Errors if the active screenshot is missing or is the wrong image.

    Exercise 1 embeds this path, so a missing or stale file renders a broken
    image in the notebook without anything else noticing.
    """
    active = repo / ACTIVE_SCREENSHOT
    if not active.is_file():
        return [f'{ACTIVE_SCREENSHOT}: missing (expected a copy of {loc.screenshot})']
    if not loc.screenshot.is_file():
        return [f'{loc.screenshot}: missing; cannot check the active screenshot']
    if active.read_bytes() != loc.screenshot.read_bytes():
        return [f'{ACTIVE_SCREENSHOT}: does not match {loc.screenshot}']
    return []


def verify(repo: Path, loc: Location) -> list[str]:
    """Errors describing anything that does not match `loc`."""
    return verify_sites(read_sources(repo), loc) + verify_screenshot(repo, loc)


def place_screenshot(repo: Path, loc: Location) -> None:
    """Copy a location's screenshot to the path exercise 1 embeds."""
    active = repo / ACTIVE_SCREENSHOT
    active.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(loc.screenshot, active)
    print(f'{ACTIVE_SCREENSHOT}: {loc.screenshot.name}', file=sys.stderr)


def rewrite_recorded_slug(text: str, slug: str) -> str:
    """The pyproject text with the recorded slug replaced.

    Raises if the line is not found exactly once. The pattern is narrower than
    TOML allows (single quotes and extra spacing are all valid and would not
    match), so a silent no-op here would report success while leaving the
    recorded location stale. No `count=1`: capping the substitution would make
    `subn` report 1 for any number of matches, leaving only the zero case
    detectable and the "exactly once" claim above untrue.
    """
    new, count = re.subn(
        r'^location = ".*"$',
        f'location = "{slug}"',
        text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit(
            'error: expected exactly 1 `location = "..."` line in '
            f'pyproject.toml, matched {count}; nothing was modified.',
        )
    return new


def retarget(repo: Path, current: Location, target: Location) -> None:
    errors = verify(repo, current)
    if errors:
        raise SystemExit(
            'error: src/ does not match the recorded location '
            f'{current.slug!r}; nothing was modified.\n  ' + '\n  '.join(errors),
        )

    # Render everything before writing anything, so a failure part-way through
    # cannot leave src/ half-retargeted.
    updated = read_sources(repo)

    for old, new in zip(sites(current), sites(target), strict=True):
        assert old.name == new.name
        if old.text == new.text:
            continue
        updated[old.filename] = updated[old.filename].replace(old.text, new.text, 1)
        print(f'{old.filename}: {old.name}', file=sys.stderr)

    # The post-condition, checked while the result is still only in memory: a
    # replacement that lands somewhere the next verify cannot find exactly once
    # would wedge the repo, since every later retarget starts by verifying.
    errors = verify_sites(updated, target)
    if errors:
        raise SystemExit(
            f'error: retargeting to {target.slug!r} would produce sources that '
            'do not verify; nothing was modified.\n  ' + '\n  '.join(errors),
        )

    # `Location.load` checks the key is present, not that the file is there.
    if not target.screenshot.is_file():
        raise SystemExit(
            f'error: {target.slug!r} names a screenshot that does not exist: '
            f'{target.screenshot}; nothing was modified.',
        )

    pyproject = repo / 'pyproject.toml'
    recorded = rewrite_recorded_slug(pyproject.read_text(), target.slug)

    # Everything is validated; now write.
    for name, text in updated.items():
        (repo / 'src' / name).write_text(text)

    place_screenshot(repo, target)
    pyproject.write_text(recorded)


def recorded_slug(repo: Path) -> str:
    with (repo / 'pyproject.toml').open('rb') as f:
        data = tomllib.load(f)
    try:
        return data['tool']['workshop']['location']
    except KeyError:
        raise SystemExit(
            'error: no [tool.workshop] location in pyproject.toml',
        ) from None


def load(slug: str) -> Location:
    path = LOCATIONS_DIR / f'{slug}.toml'
    if not path.is_file():
        available = ', '.join(sorted(p.stem for p in LOCATIONS_DIR.glob('*.toml')))
        raise SystemExit(f'error: no location {slug!r}; available: {available}')
    return Location.load(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slug', nargs='?', help='the location to switch to')
    parser.add_argument(
        '--check',
        action='store_true',
        help="verify src/ matches the recorded location; don't write anything",
    )
    args = parser.parse_args()

    current = load(recorded_slug(REPO_ROOT))

    if args.check:
        errors = verify(REPO_ROOT, current)
        for error in errors:
            print(f'error: {error}', file=sys.stderr)
        if errors:
            return 1
        print(f'src/ matches {current.slug!r}', file=sys.stderr)
        return 0

    if not args.slug:
        parser.error('a location slug is required unless --check is given')

    target = load(args.slug)
    if target.slug == current.slug:
        # Still (re)place the screenshot: this is the only path that can
        # restore it for the recorded location, and returning early here would
        # make an absent or stale image unfixable without a detour through
        # another location.
        if not target.screenshot.is_file():
            raise SystemExit(
                f'error: {target.slug!r} names a screenshot that does not '
                f'exist: {target.screenshot}',
            )
        place_screenshot(REPO_ROOT, target)
        print(f'already set to {current.slug!r}', file=sys.stderr)
        return 0

    retarget(REPO_ROOT, current, target)
    print(f'retargeted {current.slug!r} -> {target.slug!r}', file=sys.stderr)
    print(
        'next: regenerate the notebooks and execute notebook 03 to confirm '
        'the building is found',
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
