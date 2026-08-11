import json

from pathlib import Path

import location
import pytest

from tests.conftest import REPO

LOCATIONS = REPO / 'locations'


def auckland() -> location.Location:
    """A specific location, for assertions about that location's own data."""
    return location.Location.load(LOCATIONS / 'auckland.toml')


def test_load_reads_the_names():
    loc = auckland()
    assert loc.slug == 'auckland'
    assert loc.building_name == 'AUT School of Business building'
    assert loc.city == 'Auckland'
    assert loc.macro == 'Oceania'


def test_screenshot_resolves_against_the_config_directory():
    loc = auckland()
    assert loc.screenshot == LOCATIONS / 'auckland.png'
    assert loc.screenshot.is_file()


def test_absolute_screenshot_is_used_as_is(tmp_path):
    src = (LOCATIONS / 'auckland.toml').read_text()
    target = tmp_path / 'x.toml'
    target.write_text(
        src.replace('screenshot    = "auckland.png"', 'screenshot = "/tmp/abs.png"')
    )
    assert location.Location.load(target).screenshot == Path('/tmp/abs.png')


def test_feature_collection_has_no_trailing_newline():
    # TOML's ''' keeps the newline before the closing delimiter. That byte
    # would land in exercise 1's byte-count claim if it survived.
    assert not auckland().feature_collection.endswith('\n')
    assert len(auckland().feature_collection) == 910


def test_recorded_loads_the_slug_pyproject_records():
    loc = location.recorded(REPO)
    assert (LOCATIONS / f'{loc.slug}.toml').is_file()


def test_every_location_parses():
    for path in sorted(LOCATIONS.glob('*.toml')):
        loc = location.Location.load(path)
        assert loc.screenshot.is_file()
        assert json.loads(loc.feature_collection)['type'] == 'FeatureCollection'

        # Not `ring[0] == ring[-1]`: for a MultiPolygon `ring` is a list of
        # rings, and that comparison passes trivially by comparing a ring with
        # itself. Assert the shape as well as the closure.
        ring = loc.ring
        assert len(ring) >= 4, f'{path}: a closed ring needs at least 4 points'
        assert all(len(point) == 2 for point in ring), (
            f'{path}: every ring entry must be an [x, y] pair'
        )
        assert ring[0] == ring[-1], f'{path}: ring must be closed'
        assert ring[0] is not ring[-1], f'{path}: ring must be closed by value'


def _location_with(tmp_path: Path, feature_collection: str) -> Path:
    """An otherwise-valid location file carrying the given collection."""
    src = (LOCATIONS / 'auckland.toml').read_text()
    head = src[: src.index('feature_collection')]
    target = tmp_path / 'broken.toml'
    target.write_text(f"{head}feature_collection = '''\n{feature_collection}\n'''\n")
    return target


_POLYGON = """
{"type": "Feature", "properties": {},
 "geometry": {"type": "Polygon",
              "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
"""


def test_load_rejects_two_features(tmp_path):
    """Two features load fine and then disagree with themselves."""
    path = _location_with(
        tmp_path,
        f'{{"type": "FeatureCollection", "features": [{_POLYGON}, {_POLYGON}]}}',
    )
    with pytest.raises(location.LocationError, match='exactly 1 feature, found 2'):
        location.Location.load(path)


def test_load_rejects_zero_features(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection", "features": []}')
    with pytest.raises(location.LocationError, match='exactly 1 feature, found 0'):
        location.Location.load(path)


def test_load_rejects_a_multipolygon(tmp_path):
    """Otherwise this reaches `Location.wkt` as `too many values to unpack`."""
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}, "geometry": {"type": "MultiPolygon",'
        ' "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}}]}',
    )
    with pytest.raises(
        location.LocationError, match="must be a Polygon, found 'MultiPolygon'"
    ):
        location.Location.load(path)


def test_load_rejects_a_polygon_with_a_hole(tmp_path):
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}, "geometry": {"type": "Polygon",'
        ' "coordinates": [[[0, 0], [9, 0], [9, 9], [0, 0]],'
        ' [[1, 1], [2, 1], [2, 2], [1, 1]]]}}]}',
    )
    with pytest.raises(location.LocationError, match='exactly 1 ring, found 2'):
        location.Location.load(path)


def test_load_rejects_a_feature_with_no_geometry(tmp_path):
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}}]}',
    )
    with pytest.raises(location.LocationError, match='no geometry'):
        location.Location.load(path)


def test_load_rejects_something_that_is_not_a_feature_collection(tmp_path):
    path = _location_with(tmp_path, '{"type": "Polygon", "coordinates": [[[0, 0]]]}')
    with pytest.raises(location.LocationError, match='no "features" list'):
        location.Location.load(path)


def test_load_rejects_invalid_json(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection",')
    with pytest.raises(location.LocationError, match='not valid JSON'):
        location.Location.load(path)


def test_the_error_names_the_file(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection", "features": []}')
    with pytest.raises(location.LocationError, match='broken.toml'):
        location.Location.load(path)
