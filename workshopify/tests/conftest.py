"""A self-contained fixture workshop repo.

Every workshopify test runs against a repo built here under tmp_path. None of
them may touch the host repository: that is what makes the package portable,
and what lets its tests run without a guard protecting the developer's real
checkout.
"""

from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

PYPROJECT = """\
[project]
name = "fixture-workshop"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.uv]
package = false

[dependency-groups]
dev = []

[tool.workshopify]
context = "context.py"

[tool.workshopify.render]
files = ["src/*.py"]

[tool.workshopify.build]
include = ["Dockerfile"]

[tool.workshopify.params]
greeting = "hello"

[tool.jupytext]
formats = "src///py:percent,notebooks/completed///ipynb"
notebook_metadata_filter = "-all"
cell_metadata_filter = "tags,-all"

[tool.ipynb-scrubber.options]
clear-text = ""

[[tool.ipynb-scrubber.files]]
input = "notebooks/completed/01_example.ipynb"
output = "notebooks/01_example.ipynb"
notes-file = "notes/01_example.md"
"""

CONTEXT = """\
word = params['greeting']


def shout() -> str:
    return word.upper()


ASSETS = {'notebooks/assets/logo.png': 'assets/logo.png'}
"""

SRC = """\
# %% [markdown]
# # Example
#
# <!--[[[cog md(shout()) ]]]-->
# HELLO
# <!--[[[end]]]-->

# %% tags=["scrub-note"]
#| scrub-note: tags=["scrub-note"]
# a note that lands in the notes file

# %% tags=["scrub-clear"]
# <!--[[[cog cog.outl(f'word = "{word}"') ]]]-->
word = "hello"
# <!--[[[end]]]-->
print(word)
"""


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    (root / 'src').mkdir(parents=True)
    (root / 'assets').mkdir()
    (root / 'static').mkdir()
    (root / 'pyproject.toml').write_text(PYPROJECT)
    (root / 'context.py').write_text(CONTEXT)
    (root / 'src' / '01_example.py').write_text(SRC)
    (root / 'assets' / 'logo.png').write_bytes(b'\x89PNG not really')
    (root / 'Dockerfile').write_text('FROM scratch\n')
    (root / 'static' / 'README.md').write_text('participant readme\n')
    return root


def git_repo(path: Path) -> Path:
    """Turn a directory into a committed git repo (identity configured)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=path, check=True)
    subprocess.run(
        ['git', 'commit', '-q', '--allow-empty', '-m', 'init'],
        cwd=path,
        check=True,
    )
    return path
