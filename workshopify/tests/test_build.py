from __future__ import annotations

import subprocess
import tomllib

from pathlib import Path

import pytest

from conftest import git_repo
from workshopify.build import derive_pyproject
from workshopify.config import Config
from workshopify.errors import WorkshopifyError

from workshopify import build, context

KEEP = ('project', 'tool.uv')


def _setup(fixture_repo):
    config = Config.load(fixture_repo)
    return config, context.load(config)


# --- derive_pyproject ------------------------------------------------------


def test_derive_keeps_only_the_kept_tables(fixture_repo):
    derived = derive_pyproject(
        (fixture_repo / 'pyproject.toml').read_text(),
        KEEP,
        (),
    )
    data = tomllib.loads(derived)
    assert data['project']['name'] == 'fixture-workshop'
    assert data['tool'] == {'uv': {'package': False}}
    assert 'dependency-groups' not in data


def test_derive_preserves_comments_and_formatting():
    text = (
        '[project]\n'
        'name = "x"  # the name\n'
        '# a comment inside the kept table\n'
        'version = "1.0"\n'
        '\n'
        '[tool.ruff]\n'
        'line-length = 100\n'
        '\n'
        '[tool.uv]\n'
        'package = false\n'
    )
    derived = derive_pyproject(text, KEEP, ())
    assert '# the name' in derived
    assert '# a comment inside the kept table' in derived
    assert 'ruff' not in derived


def test_derive_survives_a_multiline_string_containing_a_header():
    """The hazard that killed the line-based parser: [tool.ruff] as prose."""
    text = (
        '[project]\n'
        'name = "x"\n'
        "description = '''\n"
        '[tool.ruff] is prose here, not a header\n'
        "'''\n"
    )
    data = tomllib.loads(derive_pyproject(text, KEEP, ()))
    assert '[tool.ruff]' in data['project']['description']


def test_derive_drops_the_configured_keys():
    text = (
        '[project]\n'
        'name = "x"\n'
        '\n'
        '[tool.uv]\n'
        'package = false\n'
        '\n'
        '[tool.uv.workspace]\n'
        'members = ["workshopify"]\n'
        '\n'
        '[tool.uv.sources]\n'
        'workshopify = { workspace = true }\n'
    )
    derived = derive_pyproject(
        text,
        KEEP,
        ('tool.uv.workspace', 'tool.uv.sources'),
    )
    data = tomllib.loads(derived)
    assert data['tool']['uv'] == {'package': False}


def test_derive_drop_of_an_absent_key_is_a_no_op():
    text = '[project]\nname = "x"\n'
    assert tomllib.loads(derive_pyproject(text, KEEP, ('tool.nope.deep',)))


# --- build tree assembly ---------------------------------------------------


def test_build_writes_the_complete_tree(fixture_repo, tmp_path):
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True, capture_output=True)
    config, ctx = _setup(fixture_repo)
    written = build.build(config, ctx, tmp_path)
    relative = {str(p) for p in written}

    # from include
    assert 'Dockerfile' in relative
    # from static/
    assert 'README.md' in relative
    # from ctx.assets
    assert 'notebooks/assets/logo.png' in relative
    # generated
    assert 'notebooks/01_example.ipynb' in relative
    assert 'notebooks/completed/01_example.ipynb' in relative
    assert 'notes/01_example.md' in relative
    # derived
    assert 'pyproject.toml' in relative
    assert 'uv.lock' in relative

    for path in written:
        assert (tmp_path / path).is_file(), f'{path} reported but not written'


def _tree(root):
    """Every file under root, as paths relative to it."""
    return {p.relative_to(root) for p in root.rglob('*') if p.is_file()}


def _assert_same_tree(left, right):
    """Both trees hold the same paths, and each path the same bytes."""
    assert _tree(left) == _tree(right)
    for path in sorted(_tree(left)):
        assert (right / path).read_bytes() == (left / path).read_bytes(), path


def test_build_is_idempotent(fixture_repo, tmp_path):
    """Two builds of the same source must produce identical bytes.

    This is the property that makes a from-scratch publish reviewable: if
    it fails, every publish diff is churn and the review step is useless.
    """
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True, capture_output=True)
    config, ctx = _setup(fixture_repo)
    first, second = tmp_path / 'one', tmp_path / 'two'
    build.build(config, ctx, first)
    build.build(config, ctx, second)
    # Path sets first: walking only `first` would never look at a file that
    # exists in `second` alone.
    _assert_same_tree(first, second)


def test_rebuilding_into_the_same_directory_matches_a_fresh_build(
    fixture_repo,
    tmp_path,
):
    """The real publish rebuilds into the persistent workshop worktree.

    Building into an empty directory twice cannot catch what a reused one
    does, so this asserts a second build over the first is indistinguishable
    from a single build into a clean tree.
    """
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True, capture_output=True)
    config, ctx = _setup(fixture_repo)
    reused, fresh = tmp_path / 'reused', tmp_path / 'fresh'
    build.build(config, ctx, reused)
    build.build(config, ctx, reused)
    build.build(config, ctx, fresh)
    _assert_same_tree(fresh, reused)


def test_build_does_not_report_stale_files_as_written(fixture_repo, tmp_path):
    """`written` is what this build wrote, not what happens to be present.

    The publish subtracts `written` from the branch's tracked files to flag
    cruft. If a rebuild over a reused worktree re-reported leftovers as
    written -- which globbing the destination does -- a renamed exercise
    would keep shipping its old file, silently.
    """
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True, capture_output=True)
    config, ctx = _setup(fixture_repo)
    build.build(config, ctx, tmp_path)

    stale = [
        Path('notebooks/99_renamed-away.ipynb'),
        Path('notes/99_renamed-away.md'),
        Path('notebooks/assets/old_asset.png'),
        Path('orphan_at_root.txt'),
    ]
    for relative in stale:
        planted = tmp_path / relative
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text('stale')

    written = build.build(config, ctx, tmp_path)
    for relative in stale:
        assert relative not in written, f'{relative} reported as written'


def test_build_diagnoses_an_asset_target_outside_the_repo_root(
    fixture_repo,
    tmp_path,
):
    """An ASSETS target that escapes the repo root is a config error.

    build() rebases each asset target under staging via relative_to(root); a
    target outside root makes that raise. Diagnose it as a WorkshopifyError
    rather than letting relative_to's bare ValueError escape.
    """
    config, ctx = _setup(fixture_repo)
    from workshopify.context import Context

    escaped = Context(
        namespace=ctx.namespace,
        assets={(tmp_path / 'outside.png').resolve(): fixture_repo / 'assets/logo.png'},
    )
    with pytest.raises(WorkshopifyError, match='outside'):
        build.build(config, escaped, tmp_path / 'staging')


def test_write_deps_produces_a_lock(fixture_repo, tmp_path):
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True, capture_output=True)
    config, _ = _setup(fixture_repo)
    staging = tmp_path / 'staging'
    staging.mkdir()
    build.write_deps(config, staging)
    assert (staging / 'uv.lock').is_file()
    data = tomllib.loads((staging / 'pyproject.toml').read_text())
    assert data['project']['name'] == 'fixture-workshop'
    assert set(data.get('tool', {})) == {'uv'}
    assert 'dependency-groups' not in data


# --- unwritten / is_dirty / clean ------------------------------------------


def _commit_all(wt):
    subprocess.run(['git', 'add', '-A'], cwd=wt, check=True)
    subprocess.run(['git', 'commit', '-qm', 'x'], cwd=wt, check=True)


def test_unwritten_reports_tracked_files_the_build_did_not_write(tmp_path):
    wt = git_repo(tmp_path / 'wt')
    (wt / 'kept.txt').write_text('a')
    (wt / 'orphan.txt').write_text('b')
    _commit_all(wt)
    stale = build.unwritten(wt, {Path('kept.txt')})
    assert [str(p) for p in stale] == ['orphan.txt']


def test_unwritten_ignores_untracked_files(tmp_path):
    wt = git_repo(tmp_path / 'wt')
    (wt / 'tracked.txt').write_text('a')
    _commit_all(wt)
    (wt / 'scratch.txt').write_text('b')
    assert build.unwritten(wt, {Path('tracked.txt')}) == []


def test_is_dirty_detects_modified_and_untracked(tmp_path):
    wt = git_repo(tmp_path / 'wt')
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    assert not build.is_dirty(wt)
    (wt / 'a.txt').write_text('changed')
    assert build.is_dirty(wt)
    (wt / 'a.txt').write_text('a')
    assert not build.is_dirty(wt)
    (wt / 'new.txt').write_text('n')
    assert build.is_dirty(wt)


def test_clean_removes_tracked_files_only(tmp_path):
    wt = git_repo(tmp_path / 'wt')
    (wt / 'tracked.txt').write_text('a')
    _commit_all(wt)
    (wt / 'ignored.txt').write_text('i')
    (wt / '.gitignore').write_text('ignored.txt\n')
    build.clean(wt)
    assert not (wt / 'tracked.txt').exists()
    assert (wt / 'ignored.txt').exists(), 'ignored files must survive'


# --- publish_into ----------------------------------------------------------


def _recording_build(calls, names=('built.txt',)):
    """A stand-in for build() that records its calls and writes `names`.

    publish_into's job is orchestration -- guard, then clean, then build, then
    the cruft report -- and build() itself is covered thoroughly above. Faking
    it keeps these tests about that ordering, and fast.
    """

    def fake(config, ctx, staging):
        written = set()
        for name in names:
            path = Path(staging) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('built')
            written.add(Path(name))
        calls.append((config, ctx, Path(staging)))
        return written

    return fake


def test_publish_into_refuses_a_dirty_worktree(fixture_repo, tmp_path, monkeypatch):
    config, ctx = _setup(fixture_repo)
    wt = git_repo(tmp_path / 'wt')
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    (wt / 'a.txt').write_text('dirty')

    calls = []
    monkeypatch.setattr(build, 'build', _recording_build(calls))

    with pytest.raises(WorkshopifyError) as excinfo:
        build.publish_into(
            config,
            ctx,
            wt,
            clean_first=False,
            overwrite_dirty=False,
        )
    assert 'uncommitted changes' in str(excinfo.value)
    assert calls == [], 'the build must not run'
    assert (wt / 'a.txt').read_text() == 'dirty', 'the dirty file must survive'


def test_publish_into_refuses_a_dirty_worktree_in_clean_mode(
    fixture_repo,
    tmp_path,
    monkeypatch,
):
    """The guard covers --clean too, and is checked before clean() acts.

    Narrowing it to the default mode would leave --clean deleting notebook
    edits made in Jupyter that exist nowhere else yet.
    """
    config, ctx = _setup(fixture_repo)
    wt = git_repo(tmp_path / 'wt')
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    (wt / 'new.txt').write_text('n')

    calls = []
    monkeypatch.setattr(build, 'build', _recording_build(calls))

    with pytest.raises(WorkshopifyError) as excinfo:
        build.publish_into(
            config,
            ctx,
            wt,
            clean_first=True,
            overwrite_dirty=False,
        )
    assert 'uncommitted changes' in str(excinfo.value)
    assert calls == [], 'the build must not run'
    assert (wt / 'a.txt').exists(), 'clean() must not have run'
    assert (wt / 'new.txt').exists()


def test_publish_into_overwrite_dirty_bypasses_the_guard(
    fixture_repo,
    tmp_path,
    monkeypatch,
):
    config, ctx = _setup(fixture_repo)
    wt = git_repo(tmp_path / 'wt')
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    (wt / 'a.txt').write_text('dirty')

    calls = []
    monkeypatch.setattr(build, 'build', _recording_build(calls))

    assert (
        build.publish_into(
            config,
            ctx,
            wt,
            clean_first=False,
            overwrite_dirty=True,
        )
        == 0
    )
    assert len(calls) == 1, 'the build must run'
    # The default build only writes. A dirty file it does not write survives,
    # which is why "--overwrite-dirty discards them" was the wrong wording.
    assert (wt / 'a.txt').read_text() == 'dirty'


def test_publish_into_clean_overwrite_dirty_removes_a_modified_tracked_file(
    fixture_repo,
    tmp_path,
    monkeypatch,
):
    """git rm refuses a locally modified file unless forced.

    This combination is the only way to reach clean() with a dirty worktree,
    since the guard blocks it otherwise -- so without -f the one documented
    escape hatch is exactly the broken one, and it fails with git's
    explanation thrown away.
    """
    config, ctx = _setup(fixture_repo)
    wt = git_repo(tmp_path / 'wt')
    (wt / 'a.txt').write_text('a')
    _commit_all(wt)
    (wt / 'a.txt').write_text('locally modified')

    calls = []
    monkeypatch.setattr(build, 'build', _recording_build(calls))

    assert (
        build.publish_into(
            config,
            ctx,
            wt,
            clean_first=True,
            overwrite_dirty=True,
        )
        == 0
    )
    assert not (wt / 'a.txt').exists(), 'the modified tracked file must be removed'
    assert (wt / 'built.txt').exists()


def test_publish_into_reports_a_tracked_file_the_build_did_not_write(
    fixture_repo,
    tmp_path,
    monkeypatch,
    capsys,
):
    config, ctx = _setup(fixture_repo)
    wt = git_repo(tmp_path / 'wt')
    (wt / 'orphan.txt').write_text('o')
    _commit_all(wt)

    calls = []
    monkeypatch.setattr(build, 'build', _recording_build(calls))

    assert (
        build.publish_into(
            config,
            ctx,
            wt,
            clean_first=False,
            overwrite_dirty=False,
        )
        == 0
    )
    err = capsys.readouterr().err
    assert 'not written by this build:' in err
    assert 'orphan.txt' in err
    assert '--clean' in err
