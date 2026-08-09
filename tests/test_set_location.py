import itertools
import shutil

from pathlib import Path

import location
import pytest
import set_location

REPO = Path(__file__).resolve().parent.parent

SLUGS = sorted(p.stem for p in (REPO / 'locations').glob('*.toml'))


def _fixture_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the parts of the repo the script touches."""
    repo = tmp_path / 'repo'
    (repo / 'src').mkdir(parents=True)
    (repo / 'notebooks' / 'assets').mkdir(parents=True)
    for name in set_location.SRC_FILES.values():
        shutil.copy(REPO / 'src' / name, repo / 'src' / name)
    shutil.copy(REPO / 'pyproject.toml', repo / 'pyproject.toml')
    shutil.copytree(REPO / 'locations', repo / 'locations')
    shutil.copy(
        REPO / set_location.ACTIVE_SCREENSHOT, repo / set_location.ACTIVE_SCREENSHOT
    )
    return repo


def _load(slug: str) -> location.Location:
    return location.Location.load(REPO / 'locations' / f'{slug}.toml')


def test_every_site_appears_exactly_once_in_the_real_repo():
    assert set_location.verify(REPO, _load('auckland')) == []


def test_verify_reports_a_site_it_cannot_find(tmp_path):
    repo = _fixture_repo(tmp_path)
    path = repo / 'src' / set_location.SRC_FILES['02']
    path.write_text(
        path.read_text().replace('POLYGON((174.76536299052356', 'POLYGON((0')
    )
    errors = set_location.verify(repo, _load('auckland'))
    assert any('wkt' in e for e in errors)


def test_retarget_then_back_is_byte_identical(tmp_path):
    repo = _fixture_repo(tmp_path)
    before = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES.values()
    }
    set_location.retarget(repo, _load('auckland'), _load('hiroshima'))
    assert any(
        (repo / 'src' / name).read_text() != before[name]
        for name in set_location.SRC_FILES.values()
    ), 'retarget changed nothing'
    set_location.retarget(repo, _load('hiroshima'), _load('auckland'))
    for name in set_location.SRC_FILES.values():
        assert (repo / 'src' / name).read_text() == before[name]


def test_retarget_copies_the_screenshot(tmp_path):
    repo = _fixture_repo(tmp_path)
    set_location.retarget(repo, _load('auckland'), _load('hiroshima'))
    active = repo / 'notebooks' / 'assets' / 'geojson_io.png'
    assert active.read_bytes() == (REPO / 'locations' / 'hiroshima.png').read_bytes()


def test_retarget_updates_the_recorded_slug(tmp_path):
    repo = _fixture_repo(tmp_path)
    set_location.retarget(repo, _load('auckland'), _load('hiroshima'))
    assert 'location = "hiroshima"' in (repo / 'pyproject.toml').read_text()


def test_retarget_writes_nothing_when_verification_fails(tmp_path):
    repo = _fixture_repo(tmp_path)
    path = repo / 'src' / set_location.SRC_FILES['02']
    broken = path.read_text().replace('POLYGON((174.76536299052356', 'POLYGON((0')
    path.write_text(broken)
    others = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES.values()
        if name != set_location.SRC_FILES['02']
    }
    try:
        set_location.retarget(repo, _load('auckland'), _load('hiroshima'))
    except SystemExit:
        pass
    else:
        raise AssertionError('expected SystemExit')
    assert path.read_text() == broken
    for name, text in others.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_there_is_more_than_one_location_to_round_trip():
    assert len(SLUGS) > 1, SLUGS


@pytest.mark.parametrize(('start', 'other'), list(itertools.permutations(SLUGS, 2)))
def test_every_ordered_pair_round_trips(tmp_path, start, other):
    """Retarget out and back for every pair, verifying at each step.

    The pairwise sweep is the point: a site whose match text collides with
    something in one particular location's feature collection is invisible
    until that location is the target.
    """
    repo = _fixture_repo(tmp_path)
    if start != 'auckland':
        set_location.retarget(repo, _load('auckland'), _load(start))
    assert set_location.verify(repo, _load(start)) == []

    before = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES.values()
    }

    set_location.retarget(repo, _load(start), _load(other))
    assert set_location.verify(repo, _load(other)) == [], (
        f'{start} -> {other} does not verify'
    )

    set_location.retarget(repo, _load(other), _load(start))
    assert set_location.verify(repo, _load(start)) == [], (
        f'{other} -> {start} does not verify'
    )
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} did not round-trip'


def test_verify_reports_a_missing_active_screenshot(tmp_path):
    repo = _fixture_repo(tmp_path)
    (repo / set_location.ACTIVE_SCREENSHOT).unlink()
    errors = set_location.verify(repo, _load('auckland'))
    assert any('missing' in e for e in errors), errors


def test_verify_reports_a_stale_active_screenshot(tmp_path):
    repo = _fixture_repo(tmp_path)
    shutil.copy(
        REPO / 'locations' / 'hiroshima.png', repo / set_location.ACTIVE_SCREENSHOT
    )
    errors = set_location.verify(repo, _load('auckland'))
    assert any('does not match' in e for e in errors), errors


def test_retarget_refuses_a_location_whose_screenshot_is_missing(tmp_path):
    repo = _fixture_repo(tmp_path)
    target = _load('hiroshima')
    broken = location.Location(
        slug=target.slug,
        building_name=target.building_name,
        city=target.city,
        region=target.region,
        macro=target.macro,
        screenshot=tmp_path / 'nope.png',
        feature_collection=target.feature_collection,
    )
    before = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES.values()
    }
    with pytest.raises(SystemExit, match='nope.png'):
        set_location.retarget(repo, _load('auckland'), broken)
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_retarget_refuses_when_the_recorded_slug_line_is_unmatchable(tmp_path):
    """Single quotes are valid TOML that the substitution pattern misses."""
    repo = _fixture_repo(tmp_path)
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('location = "auckland"', "location = 'auckland'")
    )
    before = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES.values()
    }
    with pytest.raises(SystemExit, match='matched 0'):
        set_location.retarget(repo, _load('auckland'), _load('hiroshima'))
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_load_rejects_an_unknown_slug():
    with pytest.raises(SystemExit, match='no location'):
        set_location.load('nowhere')


def test_recorded_slug_reads_the_table(tmp_path):
    repo = _fixture_repo(tmp_path)
    assert set_location.recorded_slug(repo) == 'auckland'


def test_recorded_slug_rejects_a_missing_table(tmp_path):
    repo = _fixture_repo(tmp_path)
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('[tool.workshop]', '[tool.nothing]')
    )
    with pytest.raises(SystemExit, match='no .tool.workshop. location'):
        set_location.recorded_slug(repo)


def test_main_same_slug_replaces_the_screenshot(monkeypatch, capsys):
    """The recorded location's own screenshot is only restorable here."""
    calls = []
    monkeypatch.setattr(
        set_location,
        'place_screenshot',
        lambda repo, loc: calls.append(loc.slug),
    )
    monkeypatch.setattr('sys.argv', ['set_location.py', 'auckland'])
    assert set_location.main() == 0
    assert calls == ['auckland']
    assert 'already set to' in capsys.readouterr().err


def test_main_unknown_slug_exits(monkeypatch):
    monkeypatch.setattr('sys.argv', ['set_location.py', 'nowhere'])
    with pytest.raises(SystemExit, match='no location'):
        set_location.main()


def test_main_check_passes_against_the_real_repo(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['set_location.py', '--check'])
    assert set_location.main() == 0
    assert "src/ matches 'auckland'" in capsys.readouterr().err
