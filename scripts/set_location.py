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

from location import (
    Location,
    derived,
    format_geojson_str,
    format_geom_pretty,
    format_geom_str,
    format_ring_points,
    format_wkt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCATIONS_DIR = REPO_ROOT / 'locations'

SRC_FILES = {
    '01': '01_is-geojson-cloud-native.py',
    '02': '02_the-well-knowns.py',
    '03': '03_reading-parquet-the-hard-way.py',
}

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
    d = derived(loc)
    one, two, three = SRC_FILES['01'], SRC_FILES['02'], SRC_FILES['03']
    return [
        Site('geojson_str', one, format_geojson_str(loc)),
        Site('geojson_bytes', one, f'{d["geojson_bytes"]} bytes'),
        Site('sample_pair', one, d['sample_pair']),
        Site('sample_pair_bytes', one, f'{d["sample_pair_bytes"]} bytes'),
        Site('ring_count', one, f'just {d["ring_count"]}'),
        Site('city', one, loc.city),
        Site('region', one, loc.region),
        Site('macro', one, loc.macro),
        Site('geom_str', two, format_geom_str(loc)),
        Site('wkt', two, format_wkt(loc)),
        Site('ring_points', two, format_ring_points(loc)),
        # Backticked: the bare coordinate also occurs six times inside the
        # geom_str/wkt/ring_points renderings, being the ring's first and last
        # point. Only the prose mention is wrapped in backticks.
        Site('sample_x', two, f'`{d["sample_x"]}`'),
        Site('wkt_wkb_ratio', two, f'{d["wkt_wkb_ratio"]}x smaller'),
        Site('geom', three, format_geom_pretty(loc)),
        Site('building_name', three, loc.building_name),
    ]


def verify(repo: Path, loc: Location) -> list[str]:
    """Errors describing any site that is not present exactly once."""
    errors: list[str] = []
    texts = {name: (repo / 'src' / name).read_text() for name in SRC_FILES.values()}

    for site in sites(loc):
        found = texts[site.filename].count(site.text)
        if found != 1:
            errors.append(
                f'{site.filename}: expected exactly 1 occurrence of site '
                f'{site.name!r}, found {found}',
            )
    return errors


def retarget(repo: Path, current: Location, target: Location) -> None:
    errors = verify(repo, current)
    if errors:
        raise SystemExit(
            'error: src/ does not match the recorded location '
            f'{current.slug!r}; nothing was modified.\n  ' + '\n  '.join(errors),
        )

    # Render everything before writing anything, so a failure part-way through
    # cannot leave src/ half-retargeted.
    updated: dict[str, str] = {}
    for name in SRC_FILES.values():
        updated[name] = (repo / 'src' / name).read_text()

    for old, new in zip(sites(current), sites(target), strict=True):
        assert old.name == new.name
        if old.text == new.text:
            continue
        updated[old.filename] = updated[old.filename].replace(old.text, new.text, 1)
        print(f'{old.filename}: {old.name}', file=sys.stderr)

    for name, text in updated.items():
        (repo / 'src' / name).write_text(text)

    active = repo / ACTIVE_SCREENSHOT
    active.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target.screenshot, active)
    print(f'{ACTIVE_SCREENSHOT}: {target.screenshot.name}', file=sys.stderr)

    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        re.sub(
            r'^location = ".*"$',
            f'location = "{target.slug}"',
            pyproject.read_text(),
            count=1,
            flags=re.MULTILINE,
        ),
    )


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
