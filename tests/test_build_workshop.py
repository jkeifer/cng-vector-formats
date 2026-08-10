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
