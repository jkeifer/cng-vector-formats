#!/usr/bin/env python3
"""Retarget the workshop to a different building.

Every exercise is built around one building: it is traced in exercise 1,
hand-encoded in exercise 2, and found in Overture in exercise 3. The polygon
appears in three renderings and five prose facts are derived from it, so doing
this by hand is a reliable way to ship stale byte counts.

The location-dependent values in src/ are rendered by the cog generators
embedded alongside them (scripts/render.py), so retargeting is: record the
new slug in pyproject.toml, re-render, place the screenshot. `--check`
re-renders in memory and reports any value that no longer matches the
recorded location.

    uv run scripts/set_location.py hiroshima
    uv run scripts/set_location.py --check
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys

from pathlib import Path

import render

from common import REPO_ROOT, ScriptError
from location import Location, recorded

LOCATIONS_DIR = REPO_ROOT / 'locations'

# Where the active location's screenshot lands. Stable, so the notebook's
# markdown reference never changes.
ACTIVE_SCREENSHOT = Path('notebooks') / 'assets' / 'geojson_io.png'


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
        raise ScriptError(
            'error: expected exactly 1 `location = "..."` line in '
            f'pyproject.toml, matched {count}; nothing was modified.',
        )
    return new


def retarget(target: Location) -> None:
    """Record the slug, re-render src/, place the screenshot.

    The slug rewrite lands first because rendering reads it back (the
    generator namespace is built from the recorded location); if rendering
    then fails, the rewrite is undone so a failure modifies nothing.
    """
    pyproject = REPO_ROOT / 'pyproject.toml'
    original = pyproject.read_text()
    pyproject.write_text(rewrite_recorded_slug(original, target.slug))
    try:
        changed = render.apply()
    except Exception:
        pyproject.write_text(original)
        raise
    for path in changed:
        print(f'rendered {path.relative_to(REPO_ROOT)}', file=sys.stderr)
    place_screenshot(REPO_ROOT, target)


def load(slug: str) -> Location:
    path = LOCATIONS_DIR / f'{slug}.toml'
    if not path.is_file():
        available = ', '.join(sorted(p.stem for p in LOCATIONS_DIR.glob('*.toml')))
        raise ScriptError(f'error: no location {slug!r}; available: {available}')
    return Location.load(path)


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    current = recorded(REPO_ROOT)

    if args.check:
        errors = render.check() + verify_screenshot(REPO_ROOT, current)
        for error in errors:
            print(f'error: {error}', file=sys.stderr)
        if errors:
            return 1
        print(f'src/ matches {current.slug!r}', file=sys.stderr)
        return 0

    if not args.slug:
        parser.error('a location slug is required unless --check is given')

    target = load(args.slug)
    # `Location.load` checks the key is present, not that the file is there.
    if not target.screenshot.is_file():
        raise ScriptError(
            f'error: {target.slug!r} names a screenshot that does not exist: '
            f'{target.screenshot}',
        )

    if target.slug == current.slug:
        # Still (re)place the screenshot: this is the only path that can
        # restore it for the recorded location, and returning early here would
        # make an absent or stale image unfixable without a detour through
        # another location.
        place_screenshot(REPO_ROOT, target)
        print(f'already set to {current.slug!r}', file=sys.stderr)
        return 0

    retarget(target)
    print(f'retargeted {current.slug!r} -> {target.slug!r}', file=sys.stderr)
    print(
        'next: regenerate the notebooks and execute notebook 03 to confirm '
        'the building is found',
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slug', nargs='?', help='the location to switch to')
    parser.add_argument(
        '--check',
        action='store_true',
        help="verify src/ matches the recorded location; don't write anything",
    )
    args = parser.parse_args()

    # The one place a failure below becomes an exit; everything under here
    # reports problems by raising. `parser.error` raises SystemExit itself,
    # by design, and passes straight through.
    try:
        return _run(args, parser)
    except ScriptError as e:
        raise SystemExit(str(e)) from e


if __name__ == '__main__':
    sys.exit(main())
