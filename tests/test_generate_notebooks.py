import json

from pathlib import Path

import generate_notebooks as gn


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
    """Escaping non-ASCII would churn every diff.

    Asserts on prose that is fixed regardless of the active workshop
    location (unlike the building name, which `set_location.py` rewrites --
    see test_generate_notebooks's sibling test for the scrubbed notebook).
    """
    dest = tmp_path / '01_is-geojson-cloud-native.ipynb'
    gn._render_completed(dest)
    raw = dest.read_text()
    assert 'facade — how' in raw
    assert '\\u2014' not in raw


def _scrub_notebook_02(tmp_path: Path) -> Path:
    """Render then scrub notebook 02 under tmp_path; return the exercise notebook.

    Notebook 02 because its em dash sits in prose that survives scrubbing --
    exercise 1's is inside a `scrub-omit` cell, so it never reaches the output.
    """
    config = gn.ProjectConfig.from_file(gn.PYPROJECT)
    entry = gn._rebase(
        next(e for e in config.files if e.input.name == '02_the-well-knowns.ipynb'),
        tmp_path,
    )
    entry.notes_file.parent.mkdir(parents=True, exist_ok=True)
    gn._render_completed(entry.input)
    gn._scrub(entry, entry.get_options(config.global_options))
    return entry.output


def test_scrub_does_not_escape_non_ascii(tmp_path):
    """The exercise notebooks are published too, so they churn the diff as well."""
    raw = _scrub_notebook_02(tmp_path).read_text()
    assert 'attributes—just' in raw
    assert '\\u2014' not in raw


def test_scrub_ends_with_a_trailing_newline(tmp_path):
    raw = _scrub_notebook_02(tmp_path).read_text()
    assert raw.endswith('}\n')
