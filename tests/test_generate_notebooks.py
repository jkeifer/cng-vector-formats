import json

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


def test_load_paths_defaults_to_empty(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text('[project]\nname = "x"\n')
    assert gn._load_paths(pyproject, 'keep') == ()
    assert gn._load_paths(pyproject, 'copy') == ()


def test_load_paths_reads_the_table(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text(
        '[tool.generate-notebooks]\n'
        'keep = ["notebooks/assets"]\n'
        'copy = ["notebooks/assets", "notebooks/data"]\n',
    )
    assert gn._load_paths(pyproject, 'keep') == ('notebooks/assets',)
    assert gn._load_paths(pyproject, 'copy') == ('notebooks/assets', 'notebooks/data')


def test_load_paths_rejects_a_non_list(tmp_path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text('[tool.generate-notebooks]\ncopy = "notebooks/assets"\n')
    try:
        gn._load_paths(pyproject, 'copy')
    except SystemExit as e:
        assert 'copy must be a list of strings' in str(e)
    else:
        raise AssertionError('expected SystemExit')


def test_unmatched_accepts_an_entry_that_resolves(tmp_path):
    _touch(tmp_path / 'notebooks' / 'assets' / 'geojson_io.png')
    assert gn._unmatched(('notebooks/assets',), tmp_path, {'notebooks'}) == []


def test_unmatched_flags_a_typo(tmp_path):
    """The failure mode this exists for: `notebook/assets`, missing the `s`."""
    _touch(tmp_path / 'notebooks' / 'assets' / 'geojson_io.png')
    assert gn._unmatched(('notebook/assets',), tmp_path, {'notebooks'}) == [
        'notebook/assets'
    ]


def test_unmatched_flags_a_path_outside_the_managed_trees(tmp_path):
    """It exists, but nothing under notebooks/ or notes/ is affected by it."""
    _touch(tmp_path / 'docs' / 'thing.png')
    assert gn._unmatched(('docs',), tmp_path, {'notebooks'}) == ['docs']


def test_warn_unmatched_writes_to_stderr(tmp_path, capsys):
    _touch(tmp_path / 'notebooks' / 'assets' / 'geojson_io.png')
    gn._warn_unmatched('keep', ('notebook/assets',), tmp_path, {'notebooks'})
    err = capsys.readouterr().err
    assert 'warning' in err
    assert "keep entry 'notebook/assets'" in err


def test_copy_inputs_overwrites_a_stale_file_in_the_output_dir(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    output = tmp_path / 'worktree'
    _touch(repo / 'notebooks' / 'assets' / 'geojson_io.png').write_text('current')
    _touch(output / 'notebooks' / 'assets' / 'geojson_io.png').write_text('stale')
    monkeypatch.setattr(gn, 'REPO_ROOT', repo)

    gn._copy_inputs(('notebooks/assets',), output)

    assert (output / 'notebooks' / 'assets' / 'geojson_io.png').read_text() == 'current'


def test_copy_inputs_creates_a_missing_destination(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    output = tmp_path / 'worktree'
    _touch(repo / 'notebooks' / 'assets' / 'geojson_io.png').write_text('current')
    monkeypatch.setattr(gn, 'REPO_ROOT', repo)

    gn._copy_inputs(('notebooks/assets',), output)

    assert (output / 'notebooks' / 'assets' / 'geojson_io.png').read_text() == 'current'


def test_copy_inputs_is_a_no_op_for_the_repo_itself(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    asset = _touch(repo / 'notebooks' / 'assets' / 'geojson_io.png')
    asset.write_text('current')
    monkeypatch.setattr(gn, 'REPO_ROOT', repo)

    gn._copy_inputs(('notebooks/assets',), repo)

    assert asset.read_text() == 'current'


def test_copy_inputs_copies_a_single_file(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    output = tmp_path / 'worktree'
    _touch(repo / 'notebooks' / 'assets' / 'a.png').write_text('current')
    monkeypatch.setattr(gn, 'REPO_ROOT', repo)

    gn._copy_inputs(('notebooks/assets/a.png',), output)

    assert (output / 'notebooks' / 'assets' / 'a.png').read_text() == 'current'


def test_rendering_twice_is_byte_identical(tmp_path):
    """The render must be a pure function of the source.

    Random cell ids made this false, which is why the generator used
    `jupytext --update` to merge into its own previous output.
    """
    first = tmp_path / 'a' / '01_is-geojson-cloud-native.ipynb'
    second = tmp_path / 'b' / '01_is-geojson-cloud-native.ipynb'
    gn._render_completed(first)
    gn._render_completed(second)
    assert first.read_bytes() == second.read_bytes()


def test_cell_ids_are_positional(tmp_path):
    dest = tmp_path / '01_is-geojson-cloud-native.ipynb'
    gn._render_completed(dest)
    ids = [c['id'] for c in json.loads(dest.read_text())['cells']]
    assert ids[:3] == [
        '01_is-geojson-cloud-native-000',
        '01_is-geojson-cloud-native-001',
        '01_is-geojson-cloud-native-002',
    ]
    assert len(set(ids)) == len(ids), 'ids must be unique'


def test_cell_ids_satisfy_nbformat(tmp_path):
    dest = tmp_path / '01_is-geojson-cloud-native.ipynb'
    gn._render_completed(dest)
    for cell in json.loads(dest.read_text())['cells']:
        assert 1 <= len(cell['id']) <= 64
        assert all(ch.isalnum() or ch in '-_' for ch in cell['id'])


def test_non_ascii_is_not_escaped(tmp_path):
    """The building name is in kanji; escaping it would churn every diff."""
    dest = tmp_path / '01_is-geojson-cloud-native.ipynb'
    gn._render_completed(dest)
    raw = dest.read_text()
    assert 'RCC文化センター' in raw
    assert '\\u6587' not in raw
