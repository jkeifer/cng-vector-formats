"""Every relative link in a generated notebook must resolve on disk.

This is the check that `workshopify check` deliberately does not make. That
command verifies a declared asset is present and matches its source in
locations/; it says nothing about whether any notebook actually points at it.
The two properties are independent, and the gap between them is real: the
exercise and completed notebooks share one markdown reference but sit in
different directories, so a reference correct in one was silently broken in
the other until they became siblings.

Requires a generated tree (`uv run workshopify generate`); the notebooks are
build artifacts and are not committed.
"""

import json
import re

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NOTEBOOK_DIRS = ('notebooks', 'notebooks-completed')

# Markdown images and links: ![alt](target) and [text](target). The target
# runs to the closing paren or to whitespace before an optional "title".
MARKDOWN_LINK = re.compile(r'!?\[[^\]]*\]\(\s*([^)\s]+)')

# Only on-disk targets are our problem. Anything with a scheme, a protocol
# -relative prefix, or a bare fragment is out of scope.
SKIP_PREFIXES = ('http://', 'https://', 'mailto:', 'data:', '//', '#')


def notebooks() -> list[Path]:
    return sorted(nb for d in NOTEBOOK_DIRS for nb in (REPO / d).glob('*.ipynb'))


def markdown_targets(notebook: Path):
    """Yield (target, cell_index) for every relative link in the notebook."""
    cells = json.loads(notebook.read_text())['cells']
    for index, cell in enumerate(cells):
        if cell['cell_type'] != 'markdown':
            continue
        source = ''.join(cell['source'])
        for target in MARKDOWN_LINK.findall(source):
            if target.startswith(SKIP_PREFIXES):
                continue
            yield target, index


def test_the_generated_tree_exists():
    """Guard the rest of the module from passing vacuously."""
    assert notebooks(), (
        'no generated notebooks found -- run `uv run workshopify generate`'
    )


@pytest.mark.parametrize('notebook', notebooks(), ids=lambda p: str(p.name))
def test_every_relative_link_resolves(notebook: Path):
    unresolved = [
        f'cell {index}: {target}'
        for target, index in markdown_targets(notebook)
        # Relative to the notebook's own directory, which is how Jupyter
        # resolves it -- and the whole reason the asset directory is a
        # sibling of both notebook directories rather than inside one.
        if not (notebook.parent / target).resolve().is_file()
    ]
    assert not unresolved, (
        f'{notebook.relative_to(REPO)} has unresolved links:\n  '
        + '\n  '.join(unresolved)
    )
