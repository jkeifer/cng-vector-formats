import shutil

from pathlib import Path

import location
import set_location

REPO = Path(__file__).resolve().parent.parent


def _fixture_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the parts of the repo the script touches."""
    repo = tmp_path / 'repo'
    (repo / 'src').mkdir(parents=True)
    (repo / 'notebooks' / 'assets').mkdir(parents=True)
    for name in set_location.SRC_FILES.values():
        shutil.copy(REPO / 'src' / name, repo / 'src' / name)
    shutil.copy(REPO / 'pyproject.toml', repo / 'pyproject.toml')
    shutil.copytree(REPO / 'locations', repo / 'locations')
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
