import tomllib

from pathlib import Path

import build_workshop

REPO = Path(__file__).resolve().parent.parent


def test_derive_pyproject_keeps_the_runtime_project():
    derived = build_workshop.derive_pyproject((REPO / 'pyproject.toml').read_text())
    data = tomllib.loads(derived)
    assert data['project']['name'] == 'cng-vector-formats'
    assert 'por-que' in ' '.join(data['project']['dependencies'])
    assert data['project']['urls']
    assert data['tool']['uv'] == {'package': False}


def test_derive_pyproject_drops_the_authoring_machinery():
    derived = build_workshop.derive_pyproject((REPO / 'pyproject.toml').read_text())
    data = tomllib.loads(derived)
    assert 'dependency-groups' not in data
    assert set(data.get('tool', {})) == {'uv'}
    for absent in ('ruff', 'pytest', 'jupytext', 'ipynb-scrubber', 'workshop'):
        assert absent not in data.get('tool', {})


def test_write_deps_produces_a_strict_subset_of_the_repo_lock(tmp_path):
    """The workshop lock is a derivation of main's, not a fresh resolution.

    Seeded with main's uv.lock and resolved with --offline, so participants
    get exactly the versions contributors develop against.
    """
    staging = tmp_path / 'staging'
    staging.mkdir()
    build_workshop.write_deps(REPO, staging)

    def packages(path):
        import re

        text = Path(path).read_text()
        return dict(
            re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', text)
        )

    main_pkgs = packages(REPO / 'uv.lock')
    workshop_pkgs = packages(staging / 'uv.lock')

    assert set(workshop_pkgs) < set(main_pkgs), 'must be a strict subset'
    drift = {k for k in workshop_pkgs if main_pkgs[k] != workshop_pkgs[k]}
    assert not drift, f'versions drifted: {drift}'
    for dev_only in ('pytest', 'ruff', 'prek', 'jupytext', 'ipynb-scrubber'):
        assert dev_only not in workshop_pkgs


def test_load_include_reads_the_table():
    include = build_workshop.load_include(REPO / 'pyproject.toml')
    assert 'Dockerfile' in include
    assert 'compose.yml' in include
    assert '.devcontainer' in include


def test_build_writes_the_complete_tree(tmp_path):
    written = build_workshop.build(REPO, tmp_path)
    relative = {str(p) for p in written}

    # from include
    assert 'Dockerfile' in relative
    assert '.devcontainer/devcontainer.json' in relative
    # from static/
    assert 'README.md' in relative
    assert '.gitignore' in relative
    # generated
    assert 'notebooks/01_is-geojson-cloud-native.ipynb' in relative
    assert 'notebooks/completed/01_is-geojson-cloud-native.ipynb' in relative
    assert 'notes/01_is-geojson-cloud-native.md' in relative
    assert 'notebooks/assets/geojson_io.png' in relative
    # derived
    assert 'pyproject.toml' in relative
    assert 'uv.lock' in relative

    for path in written:
        assert (tmp_path / path).is_file(), f'{path} reported but not written'


def test_build_uses_the_static_readme_not_the_contributor_one(tmp_path):
    build_workshop.build(REPO, tmp_path)
    assert (tmp_path / 'README.md').read_text() == (
        REPO / 'static' / 'README.md'
    ).read_text()


def _tree(root):
    """Every file under root, as paths relative to it."""
    return {p.relative_to(root) for p in root.rglob('*') if p.is_file()}


def _assert_same_tree(left, right):
    """Both trees hold the same paths, and each path the same bytes."""
    assert _tree(left) == _tree(right)
    for path in sorted(_tree(left)):
        assert (right / path).read_bytes() == (left / path).read_bytes(), path


def test_build_is_idempotent(tmp_path):
    """Two builds of the same source must produce identical bytes.

    This is the property that makes a from-scratch publish reviewable: if
    it fails, every publish diff is churn and the review step is useless.
    """
    first, second = tmp_path / 'one', tmp_path / 'two'
    build_workshop.build(REPO, first)
    build_workshop.build(REPO, second)
    # Path sets first: walking only `first` would never look at a file that
    # exists in `second` alone.
    _assert_same_tree(first, second)


def test_rebuilding_into_the_same_directory_matches_a_fresh_build(tmp_path):
    """The real publish rebuilds into the persistent workshop worktree.

    Building into an empty directory twice cannot catch what a reused one
    does, so this asserts a second build over the first is indistinguishable
    from a single build into a clean tree.
    """
    reused, fresh = tmp_path / 'reused', tmp_path / 'fresh'
    build_workshop.build(REPO, reused)
    build_workshop.build(REPO, reused)
    build_workshop.build(REPO, fresh)
    _assert_same_tree(fresh, reused)


def test_build_does_not_report_stale_files_as_written(tmp_path):
    """`written` is what this build wrote, not what happens to be present.

    The publish subtracts `written` from the branch's tracked files to flag
    cruft. If a rebuild over a reused worktree re-reported leftovers as
    written -- which globbing the destination does -- a renamed exercise
    would keep shipping its old file, silently.
    """
    build_workshop.build(REPO, tmp_path)

    stale = [
        Path('notebooks/99_renamed-away.ipynb'),
        Path('notes/99_renamed-away.md'),
        Path('.devcontainer/leftover.json'),
        Path('notebooks/assets/old_asset.png'),
        Path('orphan_at_root.txt'),
    ]
    for relative in stale:
        planted = tmp_path / relative
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text('stale')

    written = build_workshop.build(REPO, tmp_path)
    for relative in stale:
        assert relative not in written, f'{relative} reported as written'


def test_build_omits_a_configured_notes_file_that_was_never_written(tmp_path):
    """Notebook 03 declares a notes-file but has no note-tagged cells.

    Taking the notes path from the config alone would report a file that
    does not exist, making the publish's cruft check wrong in the opposite
    direction.
    """
    written = build_workshop.build(REPO, tmp_path)
    absent = Path('notes/03_reading-parquet-the-hard-way.md')
    assert not (tmp_path / absent).exists(), 'precondition: 03 writes no notes'
    assert absent not in written


def _fake_worktree(tmp_path):
    """A git repo standing in for the workshop worktree."""
    import subprocess

    wt = tmp_path / 'wt'
    wt.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=wt, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=wt, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=wt, check=True)
    return wt


def _commit_all(wt):
    import subprocess

    subprocess.run(['git', 'add', '-A'], cwd=wt, check=True)
    subprocess.run(['git', 'commit', '-qm', 'x'], cwd=wt, check=True)


def test_unwritten_reports_tracked_files_the_build_did_not_write(tmp_path):
    wt = _fake_worktree(tmp_path)
    (wt / 'kept.txt').write_text('a')
    (wt / 'orphan.txt').write_text('b')
    _commit_all(wt)
    stale = build_workshop.unwritten(wt, {Path('kept.txt')})
    assert [str(p) for p in stale] == ['orphan.txt']


def test_unwritten_ignores_untracked_files(tmp_path):
    wt = _fake_worktree(tmp_path)
    (wt / 'tracked.txt').write_text('a')
    _commit_all(wt)
    (wt / 'scratch.txt').write_text('b')
    assert build_workshop.unwritten(wt, {Path('tracked.txt')}) == []


def test_is_dirty_detects_modified_and_untracked(tmp_path):
    wt = _fake_worktree(tmp_path)
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    assert not build_workshop.is_dirty(wt)
    (wt / 'a.txt').write_text('changed')
    assert build_workshop.is_dirty(wt)
    (wt / 'a.txt').write_text('a')
    assert not build_workshop.is_dirty(wt)
    (wt / 'new.txt').write_text('n')
    assert build_workshop.is_dirty(wt)


def test_clean_removes_tracked_files_only(tmp_path):
    wt = _fake_worktree(tmp_path)
    (wt / 'tracked.txt').write_text('a')
    _commit_all(wt)
    (wt / 'ignored.txt').write_text('i')
    (wt / '.gitignore').write_text('ignored.txt\n')
    build_workshop.clean(wt)
    assert not (wt / 'tracked.txt').exists()
    assert (wt / 'ignored.txt').exists(), 'ignored files must survive'
