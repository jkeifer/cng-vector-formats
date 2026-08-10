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
    # from dist/
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


def test_build_uses_the_dist_readme_not_the_contributor_one(tmp_path):
    build_workshop.build(REPO, tmp_path)
    assert (tmp_path / 'README.md').read_text() == (
        REPO / 'dist' / 'README.md'
    ).read_text()


def test_build_is_idempotent(tmp_path):
    """Two builds of the same source must produce identical bytes.

    This is the property that makes a from-scratch publish reviewable: if
    it fails, every publish diff is churn and the review step is useless.
    """
    first, second = tmp_path / 'one', tmp_path / 'two'
    build_workshop.build(REPO, first)
    build_workshop.build(REPO, second)
    for path in sorted(p for p in first.rglob('*') if p.is_file()):
        counterpart = second / path.relative_to(first)
        assert counterpart.read_bytes() == path.read_bytes(), path
