import itertools
import shutil

from pathlib import Path

import location
import pytest
import set_location

from common import ScriptError
from conftest import REPO

SLUGS = sorted(p.stem for p in (REPO / 'locations').glob('*.toml'))

# The location the real repo currently records. Every test that starts from a
# copy of src/ must work from this rather than a hardcoded slug: src/ contains
# whichever location was last set, and a test that assumes otherwise either
# fails spuriously or -- far worse -- drives a real retarget. The guard that
# catches that lives in conftest.py, session-scoped, so it covers every module.
RECORDED = set_location.recorded_slug(REPO)

# Any other location, for retargeting away and back.
OTHER = next(slug for slug in SLUGS if slug != RECORDED)


def _fixture_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the parts of the repo the script touches."""
    repo = tmp_path / 'repo'
    (repo / 'src').mkdir(parents=True)
    (repo / 'notebooks' / 'assets').mkdir(parents=True)
    for name in set_location.SRC_FILES:
        shutil.copy(REPO / 'src' / name, repo / 'src' / name)
    shutil.copy(REPO / 'pyproject.toml', repo / 'pyproject.toml')
    shutil.copytree(REPO / 'locations', repo / 'locations')
    shutil.copy(
        REPO / set_location.ACTIVE_SCREENSHOT, repo / set_location.ACTIVE_SCREENSHOT
    )
    return repo


def _isolate(monkeypatch, repo: Path) -> Path:
    """Point the module's repo-wide constants at a throwaway copy."""
    monkeypatch.setattr(set_location, 'REPO_ROOT', repo)
    monkeypatch.setattr(set_location, 'LOCATIONS_DIR', repo / 'locations')
    return repo


def _load(slug: str) -> location.Location:
    return location.Location.load(REPO / 'locations' / f'{slug}.toml')


def _break_the_wkt(repo: Path) -> str:
    """Replace the recorded location's WKT literal with a bogus one."""
    path = repo / 'src' / set_location.SRC_WELL_KNOWNS
    text = path.read_text()
    wkt = _load(RECORDED).wkt
    assert wkt in text, 'the fixture does not contain the recorded WKT'
    broken = text.replace(wkt, 'POLYGON((0 0))')
    path.write_text(broken)
    return broken


def test_every_site_appears_exactly_once_in_the_real_repo():
    assert set_location.verify(REPO, _load(RECORDED)) == []


def test_verify_reports_a_site_it_cannot_find(tmp_path):
    repo = _fixture_repo(tmp_path)
    _break_the_wkt(repo)
    errors = set_location.verify(repo, _load(RECORDED))
    assert any('wkt' in e for e in errors)


def test_retarget_then_back_is_byte_identical(tmp_path):
    repo = _fixture_repo(tmp_path)
    before = {
        name: (repo / 'src' / name).read_text() for name in set_location.SRC_FILES
    }
    set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    assert any(
        (repo / 'src' / name).read_text() != before[name]
        for name in set_location.SRC_FILES
    ), 'retarget changed nothing'
    set_location.retarget(repo, _load(OTHER), _load(RECORDED))
    for name in set_location.SRC_FILES:
        assert (repo / 'src' / name).read_text() == before[name]


def test_retarget_copies_the_screenshot(tmp_path):
    repo = _fixture_repo(tmp_path)
    set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    active = repo / set_location.ACTIVE_SCREENSHOT
    assert active.read_bytes() == _load(OTHER).screenshot.read_bytes()


def test_retarget_updates_the_recorded_slug(tmp_path):
    repo = _fixture_repo(tmp_path)
    set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    assert f'location = "{OTHER}"' in (repo / 'pyproject.toml').read_text()


def test_retarget_writes_nothing_when_verification_fails(tmp_path):
    repo = _fixture_repo(tmp_path)
    path = repo / 'src' / set_location.SRC_WELL_KNOWNS
    broken = _break_the_wkt(repo)
    others = {
        name: (repo / 'src' / name).read_text()
        for name in set_location.SRC_FILES
        if name != set_location.SRC_WELL_KNOWNS
    }
    try:
        set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    except ScriptError:
        pass
    else:
        raise AssertionError('expected ScriptError')
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
    if start != RECORDED:
        set_location.retarget(repo, _load(RECORDED), _load(start))
    assert set_location.verify(repo, _load(start)) == []

    before = {
        name: (repo / 'src' / name).read_text() for name in set_location.SRC_FILES
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
    errors = set_location.verify(repo, _load(RECORDED))
    assert any('missing' in e for e in errors), errors


def test_verify_reports_a_stale_active_screenshot(tmp_path):
    repo = _fixture_repo(tmp_path)
    shutil.copy(_load(OTHER).screenshot, repo / set_location.ACTIVE_SCREENSHOT)
    errors = set_location.verify(repo, _load(RECORDED))
    assert any('does not match' in e for e in errors), errors


def test_retarget_refuses_a_location_whose_screenshot_is_missing(tmp_path):
    repo = _fixture_repo(tmp_path)
    target = _load(OTHER)
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
        name: (repo / 'src' / name).read_text() for name in set_location.SRC_FILES
    }
    with pytest.raises(ScriptError, match='nope.png'):
        set_location.retarget(repo, _load(RECORDED), broken)
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_retarget_refuses_when_the_recorded_slug_line_is_unmatchable(tmp_path):
    """Single quotes are valid TOML that the substitution pattern misses."""
    repo = _fixture_repo(tmp_path)
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace(
            f'location = "{RECORDED}"', f"location = '{RECORDED}'"
        )
    )
    before = {
        name: (repo / 'src' / name).read_text() for name in set_location.SRC_FILES
    }
    with pytest.raises(ScriptError, match='matched 0'):
        set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_retarget_refuses_when_the_recorded_slug_line_is_ambiguous(tmp_path):
    """A second matching line means we cannot tell which one is authoritative."""
    repo = _fixture_repo(tmp_path)
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text() + f'\n[tool.elsewhere]\nlocation = "{OTHER}"\n'
    )
    before = {
        name: (repo / 'src' / name).read_text() for name in set_location.SRC_FILES
    }
    with pytest.raises(ScriptError, match='matched 2'):
        set_location.retarget(repo, _load(RECORDED), _load(OTHER))
    for name, text in before.items():
        assert (repo / 'src' / name).read_text() == text, f'{name} was modified'


def test_rewrite_recorded_slug_replaces_the_one_line():
    text = '[tool.workshop]\nlocation = "old"\n'
    assert set_location.rewrite_recorded_slug(text, 'new') == (
        '[tool.workshop]\nlocation = "new"\n'
    )


def test_load_rejects_an_unknown_slug():
    with pytest.raises(ScriptError, match='no location'):
        set_location.load('nowhere')


def test_recorded_slug_reads_the_table(tmp_path):
    repo = _fixture_repo(tmp_path)
    assert set_location.recorded_slug(repo) == RECORDED


def test_recorded_slug_rejects_a_missing_table(tmp_path):
    repo = _fixture_repo(tmp_path)
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('[tool.workshop]', '[tool.nothing]')
    )
    with pytest.raises(ScriptError, match='no .tool.workshop. location'):
        set_location.recorded_slug(repo)


def test_main_same_slug_replaces_the_screenshot(tmp_path, monkeypatch, capsys):
    """The recorded location's own screenshot is only restorable here."""
    repo = _isolate(monkeypatch, _fixture_repo(tmp_path))
    active = repo / set_location.ACTIVE_SCREENSHOT
    active.unlink()

    monkeypatch.setattr('sys.argv', ['set_location.py', RECORDED])
    assert set_location.main() == 0

    assert active.read_bytes() == _load(RECORDED).screenshot.read_bytes()
    assert 'already set to' in capsys.readouterr().err


def test_main_retargets_an_isolated_repo(tmp_path, monkeypatch):
    repo = _isolate(monkeypatch, _fixture_repo(tmp_path))
    monkeypatch.setattr('sys.argv', ['set_location.py', OTHER])
    assert set_location.main() == 0
    assert set_location.recorded_slug(repo) == OTHER
    assert set_location.verify(repo, _load(OTHER)) == []


def test_main_check_reports_the_recorded_location(tmp_path, monkeypatch, capsys):
    repo = _isolate(monkeypatch, _fixture_repo(tmp_path))
    monkeypatch.setattr('sys.argv', ['set_location.py', '--check'])
    assert set_location.main() == 0
    assert f'src/ matches {RECORDED!r}' in capsys.readouterr().err
    assert set_location.verify(repo, _load(RECORDED)) == []


def test_main_check_fails_on_a_drifted_repo(tmp_path, monkeypatch, capsys):
    repo = _isolate(monkeypatch, _fixture_repo(tmp_path))
    _break_the_wkt(repo)
    monkeypatch.setattr('sys.argv', ['set_location.py', '--check'])
    assert set_location.main() == 1
    assert 'wkt' in capsys.readouterr().err


def test_main_unknown_slug_exits(tmp_path, monkeypatch):
    """The CLI, unlike `load` above, turns the failure into an exit.

    Same message either way: main() re-raises what it caught, so the boundary
    decides the exit and nothing else changes.
    """
    _isolate(monkeypatch, _fixture_repo(tmp_path))
    monkeypatch.setattr('sys.argv', ['set_location.py', 'nowhere'])
    with pytest.raises(SystemExit, match='no location'):
        set_location.main()


def test_check_passes_against_the_real_repo():
    """The read-only half of `main --check`, against the actual checkout."""
    assert set_location.verify(REPO, _load(RECORDED)) == []
