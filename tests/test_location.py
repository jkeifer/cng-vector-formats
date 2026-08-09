import json
import re

from pathlib import Path

import location

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
    # would land in the "910 bytes" claim if it survived.
    assert not auckland().feature_collection.endswith('\n')
    assert len(auckland().feature_collection) == 910


def test_geojson_str_matches_the_current_source():
    text = (REPO / 'src' / '01_is-geojson-cloud-native.py').read_text()
    assert location.format_geojson_str(auckland()) == _payload(
        r'geojson_str = """(.*?)"""', text
    )


def test_geom_str_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    assert location.format_geom_str(auckland()) == _payload(
        r'geom_str = """(.*?)"""', text
    )


def test_wkt_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    literal = re.search(r"^wkt = '(POLYGON.*?)'$", text, re.MULTILINE).group(1)
    assert location.format_wkt(auckland()) == literal


def test_ring_points_matches_the_current_source():
    text = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    literal = re.search(r'ring_points = \[\n(.*?)\n\]', text, re.DOTALL).group(1)
    assert location.format_ring_points(auckland()) == literal


def test_geom_pretty_matches_the_current_source():
    text = (REPO / 'src' / '03_reading-parquet-the-hard-way.py').read_text()
    literal = _payload(r'geom = json\.loads\("""(.*?)"""\)', text)
    assert location.format_geom_pretty(auckland()) == literal


def test_every_location_parses():
    for path in sorted(LOCATIONS.glob('*.toml')):
        loc = location.Location.load(path)
        assert loc.screenshot.is_file()
        assert json.loads(loc.feature_collection)['type'] == 'FeatureCollection'
        assert loc.ring[0] == loc.ring[-1], 'ring must be closed'


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


def test_derived_values_appear_verbatim_in_the_sources():
    d = location.derived(auckland())
    one = (REPO / 'src' / '01_is-geojson-cloud-native.py').read_text()
    two = (REPO / 'src' / '02_the-well-knowns.py').read_text()
    assert one.count(f'{d["geojson_bytes"]} bytes') == 1
    assert one.count(d['sample_pair']) == 1
    assert one.count(f'{d["sample_pair_bytes"]} bytes') == 1
    assert two.count(f'{d["wkt_wkb_ratio"]}x smaller') == 1
    # Backticked, so it does not collide with the six bare occurrences inside
    # the geom_str/wkt/ring_points renderings.
    assert two.count(f'`{d["sample_x"]}`') == 1
