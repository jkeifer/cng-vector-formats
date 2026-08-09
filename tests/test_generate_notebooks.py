from pathlib import Path

import generate_notebooks as gn


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x')
    return path


def test_stale_paths_reports_unclaimed_files(tmp_path):
    _touch(tmp_path / 'notebooks' / 'assets' / 'geojson_io.png')
    stale = gn._stale_paths([], tmp_path, {'notebooks'})
    assert [p.name for p in stale] == ['geojson_io.png']


def test_stale_paths_honours_a_kept_directory(tmp_path):
    _touch(tmp_path / 'notebooks' / 'assets' / 'geojson_io.png')
    _touch(tmp_path / 'notebooks' / 'leftover.ipynb')
    stale = gn._stale_paths([], tmp_path, {'notebooks'}, keep=('notebooks/assets',))
    assert [p.name for p in stale] == ['leftover.ipynb']


def test_stale_paths_honours_a_kept_file(tmp_path):
    _touch(tmp_path / 'notebooks' / 'assets' / 'a.png')
    _touch(tmp_path / 'notebooks' / 'assets' / 'b.png')
    stale = gn._stale_paths(
        [], tmp_path, {'notebooks'}, keep=('notebooks/assets/a.png',)
    )
    assert [p.name for p in stale] == ['b.png']


def test_load_keep_defaults_to_empty(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text('[project]\nname = "x"\n')
    assert gn._load_keep(pyproject) == ()


def test_load_keep_reads_the_table(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text(
        '[tool.generate-notebooks]\nkeep = ["notebooks/assets"]\n',
    )
    assert gn._load_keep(pyproject) == ('notebooks/assets',)


def test_load_keep_rejects_a_non_list(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text('[tool.generate-notebooks]\nkeep = "notebooks/assets"\n')
    try:
        gn._load_keep(pyproject)
    except SystemExit as e:
        assert 'must be a list of strings' in str(e)
    else:
        raise AssertionError('expected SystemExit')
