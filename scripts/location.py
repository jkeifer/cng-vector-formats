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

# The point whose condensed rendering exercise 1 quotes when it talks about how
# many bytes a coordinate pair costs.
SAMPLE_POINT_INDEX = 2


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
            raise SystemExit(
                f'error: {path} is missing {", ".join(sorted(missing))}',
            )

        # A relative screenshot is relative to the config file that names it,
        # which keeps locations/ self-contained. Absolute is used as-is.
        screenshot = Path(data['screenshot'])
        if not screenshot.is_absolute():
            screenshot = path.parent / screenshot

        return cls(
            slug=path.stem,
            building_name=data['building_name'],
            city=data['city'],
            region=data['region'],
            macro=data['macro'],
            screenshot=screenshot,
            # TOML's ''' keeps the newline before the closing delimiter; that
            # byte would otherwise land in exercise 1's byte-count claim.
            feature_collection=data['feature_collection'].strip(),
        )

    @property
    def geometry(self) -> dict:
        return json.loads(self.feature_collection)['features'][0]['geometry']

    @property
    def ring(self) -> list[list[float]]:
        return self.geometry['coordinates'][0]


def format_geojson_str(loc: Location) -> str:
    """Exercise 1: the FeatureCollection, exactly as the reader pasted it."""
    return loc.feature_collection


def format_geom_str(loc: Location) -> str:
    """Exercise 2: the geometry, with each coordinate pair on one line."""
    coords = ',\n'.join(f'        [{x}, {y}]' for x, y in loc.ring)
    return '{\n    "coordinates": [[\n' + coords + '\n    ]],\n    "type": "Polygon"\n}'


def format_wkt(loc: Location) -> str:
    """Exercise 2: the WKT the reader is asked to write by hand."""
    return 'POLYGON((' + ', '.join(f'{x} {y}' for x, y in loc.ring) + '))'


def format_ring_points(loc: Location) -> str:
    """Exercise 2: the body of the ring_points list, without its brackets."""
    return ',\n'.join(f'    ({x}, {y})' for x, y in loc.ring) + ','


def format_geom_pretty(loc: Location) -> str:
    """Exercise 3: the geometry alone, pretty-printed."""
    return json.dumps(loc.geometry, indent=2)


def derived(loc: Location) -> dict[str, str]:
    """The facts the prose asserts, computed rather than written down.

    All returned as strings: these are substituted into source text, and
    formatting them here keeps rounding in one place.
    """
    ring = loc.ring
    pair = json.dumps(ring[SAMPLE_POINT_INDEX], separators=(',', ':')) + ','
    wkt = format_wkt(loc)
    # 1 byte endianness + 4 type + 4 ring count + 4 point count + 16 per point.
    wkb_size = 13 + 16 * len(ring)

    return {
        'geojson_bytes': str(len(loc.feature_collection)),
        'sample_pair': pair,
        'sample_pair_bytes': str(len(pair)),
        'ring_count': str(len(ring)),
        'sample_x': repr(ring[0][0]),
        'wkt_wkb_ratio': f'{len(wkt) / wkb_size:.1f}',
    }
