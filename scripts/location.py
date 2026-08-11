"""The workshop's location data: one building, rendered every way the
exercises need it.

A location file carries only what cannot be computed -- the FeatureCollection
as pasted from geojson.io, and the names used in prose. Everything the sources
actually contain is derived from those here, so a location file cannot drift
out of agreement with itself.
"""

from __future__ import annotations

import json
import tomllib

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from common import ScriptError

# The point whose condensed rendering exercise 1 quotes when it talks about how
# many bytes a coordinate pair costs.
SAMPLE_POINT_INDEX = 2


class LocationError(ScriptError, ValueError):
    """A location file that cannot be loaded, naming the file and the reason.

    This module is the data model: it has no `main()` and no argparse, and a
    caller may well want to load every location and report all the bad ones,
    or load two to compare them. Raising `SystemExit` here made both
    impossible. Whichever script loaded the file decides what a failure costs.

    Also a `ValueError` because that is what this is -- a value that does not
    parse -- so a caller that never heard of this module still catches it.
    """


def _validate_feature_collection(path: Path, text: str) -> None:
    """Reject anything the exercises cannot render as one building.

    `geometry` and `ring` index straight into the parsed JSON, and every
    consumer assumes a single outer ring. Two failures this catches:

      * Two features load fine and then disagree with themselves -- exercise 1
        shows the whole collection while exercises 2 and 3 use only the first.
      * A MultiPolygon reaches `Location.wkt` as a list of rings and fails
        there with `too many values to unpack (expected 2, got 5)`, naming
        nothing.

    Checked at load time so the message can name the file that is wrong.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LocationError(
            f'error: {path}: feature_collection is not valid JSON: {e}',
        ) from None

    features = data.get('features') if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise LocationError(
            f'error: {path}: feature_collection has no "features" list; it must '
            'be a GeoJSON FeatureCollection as pasted from geojson.io',
        )
    if len(features) != 1:
        raise LocationError(
            f'error: {path}: feature_collection must hold exactly 1 feature, '
            f'found {len(features)}. The workshop is built around one building: '
            'exercise 1 shows the whole collection, exercises 2 and 3 use only '
            'the first feature, so more than one silently disagrees.',
        )

    geometry = features[0].get('geometry') if isinstance(features[0], dict) else None
    if not isinstance(geometry, dict):
        raise LocationError(f'error: {path}: the feature has no geometry')

    kind = geometry.get('type')
    if kind != 'Polygon':
        raise LocationError(
            f'error: {path}: the geometry must be a Polygon, found {kind!r}. '
            'Trace the building as a single polygon.',
        )

    rings = geometry.get('coordinates')
    if not isinstance(rings, list) or len(rings) != 1:
        found = len(rings) if isinstance(rings, list) else 'no'
        raise LocationError(
            f'error: {path}: the Polygon must have exactly 1 ring, found '
            f'{found}. Exercise 2 hand-encodes a single ring; holes have '
            'nowhere to go.',
        )


def utf8_len(text: str) -> int:
    """The byte count, which is what exercise 1's prose actually claims.

    `len()` on a str counts characters. That agreed with the byte count only
    for as long as every location was pure ASCII; a building name in Japanese
    made the two differ by 12.
    """
    return len(text.encode())


@dataclass(frozen=True, slots=True)
class Location:
    slug: str
    building_name: str
    city: str
    region: str
    macro: str
    screenshot: Path
    feature_collection: str

    @classmethod
    def load(cls, path: Path) -> Self:
        with path.open('rb') as f:
            data = tomllib.load(f)

        missing = {
            'building_name',
            'city',
            'region',
            'macro',
            'screenshot',
            'feature_collection',
        } - data.keys()
        if missing:
            raise LocationError(
                f'error: {path} is missing {", ".join(sorted(missing))}',
            )

        # A relative screenshot is relative to the config file that names it,
        # which keeps locations/ self-contained. Absolute is used as-is.
        screenshot = Path(data['screenshot'])
        if not screenshot.is_absolute():
            screenshot = path.parent / screenshot

        # TOML's ''' keeps the newline before the closing delimiter; that byte
        # would otherwise land in exercise 1's byte-count claim.
        feature_collection = data['feature_collection'].strip()
        _validate_feature_collection(path, feature_collection)

        return cls(
            slug=path.stem,
            building_name=data['building_name'],
            city=data['city'],
            region=data['region'],
            macro=data['macro'],
            screenshot=screenshot,
            feature_collection=feature_collection,
        )

    @property
    def geometry(self) -> dict:
        return json.loads(self.feature_collection)['features'][0]['geometry']

    @property
    def ring(self) -> list[list[float]]:
        return self.geometry['coordinates'][0]

    @property
    def geom_str(self) -> str:
        """Exercise 2: the geometry, with each coordinate pair on one line."""
        coords = ',\n'.join(f'        [{x}, {y}]' for x, y in self.ring)
        return (
            '{\n    "coordinates": [[\n'
            + coords
            + '\n    ]],\n    "type": "Polygon"\n}'
        )

    @property
    def wkt(self) -> str:
        """Exercise 2: the WKT the reader is asked to write by hand."""
        return 'POLYGON((' + ', '.join(f'{x} {y}' for x, y in self.ring) + '))'

    @property
    def ring_points(self) -> str:
        """Exercise 2: the body of the ring_points list, without its brackets."""
        return ',\n'.join(f'    ({x}, {y})' for x, y in self.ring) + ','

    @property
    def geom_pretty(self) -> str:
        """Exercise 3: the geometry alone, pretty-printed."""
        return json.dumps(self.geometry, indent=2)

    @property
    def sample_pair(self) -> str:
        """The condensed pair exercise 1 quotes when it prices a coordinate.

        Every other fact the prose asserts is derived inline by the template
        generator that states it, next to the claim it backs. This one is a
        property only because its generator uses it twice -- once to show the
        pair, once to count its bytes -- and would otherwise derive it twice.
        """
        pair = self.ring[SAMPLE_POINT_INDEX]
        return json.dumps(pair, separators=(',', ':')) + ','


def recorded(repo: Path) -> Location:
    """The location src/ currently contains, per pyproject.toml's record."""
    with (repo / 'pyproject.toml').open('rb') as f:
        data = tomllib.load(f)
    try:
        slug = data['tool']['workshop']['location']
    except KeyError:
        raise LocationError(
            'error: no [tool.workshop] location in pyproject.toml',
        ) from None
    return Location.load(repo / 'locations' / f'{slug}.toml')
