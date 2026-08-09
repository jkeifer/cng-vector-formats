import json
import re

from pathlib import Path

import location
import pytest
import set_location

REPO = Path(__file__).resolve().parent.parent
LOCATIONS = REPO / 'locations'


def _payload(pattern: str, text: str) -> str:
    """The one match with a real payload.

    The `#| scrub-note:` lines carry near-identical assignments whose value is
    placeholder text like "PASTE YOUR GEOJSON GEOMETRY HERE"; length
    discriminates them from the real one.
    """
    matches = [m for m in re.findall(pattern, text, re.DOTALL) if len(m) > 100]
    assert len(matches) == 1, f'expected 1 payload for {pattern!r}, got {len(matches)}'
    return matches[0]


def auckland() -> location.Location:
    """A specific location, for assertions about that location's own data."""
    return location.Location.load(LOCATIONS / 'auckland.toml')


def recorded() -> location.Location:
    """Whichever location `src/` currently contains.

    Deliberately separate from `auckland()`. The tests below that read `src/`
    assert that the formatters reproduce what is actually there, which is a
    location-independent contract; naming a location in them instead only
    happened to hold while that location was the one set, and broke the moment
    the workshop was retargeted.
    """
    return location.Location.load(
        LOCATIONS / f'{set_location.recorded_slug(REPO)}.toml'
    )


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
    # would land in the "910 bytes" claim if it survived.
    assert not auckland().feature_collection.endswith('\n')
    assert len(auckland().feature_collection) == 910


def test_geojson_str_matches_the_current_source():
    text = (REPO / 'src' / '01_is-geojson-cloud-native.py').read_text()
    assert location.format_geojson_str(recorded()) == _payload(
        r'geojson_str = """(.*?)"""', text
    )


def test_geom_str_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    assert location.format_geom_str(recorded()) == _payload(
        r'geom_str = """(.*?)"""', text
    )


def test_wkt_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    literal = re.search(r"^wkt = '(POLYGON.*?)'$", text, re.MULTILINE).group(1)
    assert location.format_wkt(recorded()) == literal


def test_ring_points_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    literal = re.search(r'ring_points = \[\n(.*?)\n\]', text, re.DOTALL).group(1)
    assert location.format_ring_points(recorded()) == literal


def test_geom_pretty_matches_the_current_source():
    text = (REPO / 'src' / '03_reading-parquet-the-hard-way.py').read_text()
    literal = _payload(r'geom = json\.loads\("""(.*?)"""\)', text)
    assert location.format_geom_pretty(recorded()) == literal


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
    with pytest.raises(SystemExit, match='exactly 1 feature, found 2'):
        location.Location.load(path)


def test_load_rejects_zero_features(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection", "features": []}')
    with pytest.raises(SystemExit, match='exactly 1 feature, found 0'):
        location.Location.load(path)


def test_load_rejects_a_multipolygon(tmp_path):
    """Otherwise this reaches format_wkt as `too many values to unpack`."""
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}, "geometry": {"type": "MultiPolygon",'
        ' "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}}]}',
    )
    with pytest.raises(SystemExit, match="must be a Polygon, found 'MultiPolygon'"):
        location.Location.load(path)


def test_load_rejects_a_polygon_with_a_hole(tmp_path):
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}, "geometry": {"type": "Polygon",'
        ' "coordinates": [[[0, 0], [9, 0], [9, 9], [0, 0]],'
        ' [[1, 1], [2, 1], [2, 2], [1, 1]]]}}]}',
    )
    with pytest.raises(SystemExit, match='exactly 1 ring, found 2'):
        location.Location.load(path)


def test_load_rejects_a_feature_with_no_geometry(tmp_path):
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {}}]}',
    )
    with pytest.raises(SystemExit, match='no geometry'):
        location.Location.load(path)


def test_load_rejects_something_that_is_not_a_feature_collection(tmp_path):
    path = _location_with(tmp_path, '{"type": "Polygon", "coordinates": [[[0, 0]]]}')
    with pytest.raises(SystemExit, match='no "features" list'):
        location.Location.load(path)


def test_load_rejects_invalid_json(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection",')
    with pytest.raises(SystemExit, match='not valid JSON'):
        location.Location.load(path)


def test_the_error_names_the_file(tmp_path):
    path = _location_with(tmp_path, '{"type": "FeatureCollection", "features": []}')
    with pytest.raises(SystemExit, match='broken.toml'):
        location.Location.load(path)


def test_derived_values_for_auckland():
    d = location.derived(auckland())
    assert d['geojson_bytes'] == '910'
    assert d['ring_count'] == '6'
    assert d['sample_pair'] == '[174.76510987799577,-36.853728372411425],'
    assert d['sample_pair_bytes'] == '41'
    assert d['sample_x'] == '174.76536299052356'
    assert d['wkt_wkb_ratio'] == '2.2'


def test_derived_values_for_hiroshima():
    loc = location.Location.load(LOCATIONS / 'hiroshima.toml')
    d = location.derived(loc)
    assert d['geojson_bytes'] == '707'
    assert d['ring_count'] == '5'
    assert d['sample_pair'] == '[132.469393,34.3947249],'
    assert d['sample_pair_bytes'] == '24'
    assert d['sample_x'] == '132.4693292'
    assert d['wkt_wkb_ratio'] == '1.4'


def test_geojson_bytes_counts_bytes_not_characters(tmp_path):
    """`len()` on a str counts characters; exercise 1 claims bytes."""
    path = _location_with(
        tmp_path,
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {"buildingName": "文化"}, "geometry":'
        ' {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1],'
        ' [0, 0]]]}}]}',
    )
    loc = location.Location.load(path)
    assert '文化' in loc.feature_collection
    characters = len(loc.feature_collection)
    assert location.derived(loc)['geojson_bytes'] == str(characters + 4)


def test_utf8_len_is_the_encoded_length():
    assert location.utf8_len('abc') == 3
    assert location.utf8_len('文化') == 6


def test_derived_values_appear_verbatim_in_the_sources():
    d = location.derived(recorded())
    one = (REPO / 'src' / '01_is-geojson-cloud-native.py').read_text()
    two = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    assert one.count(f'{d["geojson_bytes"]} bytes') == 1
    assert one.count(d['sample_pair']) == 1
    assert one.count(f'{d["sample_pair_bytes"]} bytes') == 1
    assert two.count(f'{d["wkt_wkb_ratio"]}x smaller') == 1
    # Backticked, so it does not collide with the six bare occurrences inside
    # the geom_str/wkt/ring_points renderings.
    assert two.count(f'`{d["sample_x"]}`') == 1
