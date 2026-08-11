#!/usr/bin/env python3
"""Render cog-templated sources, entirely in memory.

The files named by [tool.render] in pyproject.toml carry cog generators in
comments; the values those generators produce sit inline in the file, so the
sources read normally and re-rendering them is a no-op until the underlying
data changes. This module knows nothing about what the generators compute:
their namespace comes from the configured context module, so the same
machinery serves any repo that templates its sources this way.

    [tool.render]
    files = ["src/*.py"]
    context = "scripts/workshop_context.py"

Three operations:

    apply()          re-render every configured file in place (cog -r)
    check()          error strings if any file is stale (cog --check)
    publish(text)    the text with markers and generators stripped (cog -d),
                     validated as a sound py:percent document

`uv run scripts/render.py` applies; `--check` reports staleness and exits
nonzero. Failures raise ScriptError/PublishError below the CLI, which is the
only place they become an exit.
"""

from __future__ import annotations

import argparse
import difflib
import io
import sys
import tomllib

from pathlib import Path

import jupytext

from cogapp import Cog
from common import REPO_ROOT, ScriptError

# HTML-comment forms of cog's markers, so a marker that ever leaked into
# rendered markdown would at least be invisible. One definition, used by
# every operation and stated in the docs -- do not vary per file.
MARKERS = ('<!--[[[cog', ']]]-->', '<!--[[[end]]]-->')

# `md()` emits generator output as markdown-cell comment lines. It is defined
# here, not in the context module, because it needs the `cog` object that
# cogapp injects into the generator namespace at run time.
PROLOGUE = "def md(o): cog.outl('\\n'.join('# ' + l for l in str(o).split('\\n')))"


class PublishError(ScriptError):
    """Stripped output that is structurally unsound and must not ship."""


def _config() -> tuple[list[Path], Path]:
    """The configured file list (expanded) and context module path."""
    with (REPO_ROOT / 'pyproject.toml').open('rb') as f:
        table = tomllib.load(f).get('tool', {}).get('render')
    if not table:
        raise ScriptError('error: no [tool.render] table in pyproject.toml')
    files = sorted(
        path for pattern in table['files'] for path in REPO_ROOT.glob(pattern)
    )
    if not files:
        raise ScriptError(
            f'error: [tool.render] files matched nothing: {table["files"]}'
        )
    return files, REPO_ROOT / table['context']


def context() -> dict:
    """The generator namespace: the context module's, after executing it.

    Executed fresh on every call, so a caller that just rewrote the recorded
    state (set_location.py) gets a namespace reflecting the rewrite.
    """
    _, path = _config()
    namespace: dict = {'__file__': str(path)}
    exec(compile(path.read_text(), str(path), 'exec'), namespace)  # noqa: S102
    return namespace


def _run(text: str, namespace: dict, fname: str, *, delete_code: bool) -> str:
    cog = Cog()
    options = cog.options
    options.begin_spec, options.end_spec, options.end_output = MARKERS
    options.prologue = PROLOGUE
    options.delete_code = delete_code
    out = io.StringIO()
    cog.process_file(io.StringIO(text), out, fname=fname, globals=dict(namespace))
    return out.getvalue()


def _rendered(namespace: dict | None = None) -> dict[Path, str]:
    """Every configured file re-rendered, in memory, none written."""
    files, _ = _config()
    namespace = namespace if namespace is not None else context()
    return {
        path: _run(path.read_text(), namespace, str(path), delete_code=False)
        for path in files
    }


def apply() -> list[Path]:
    """Re-render every configured file in place; the files that changed.

    Everything renders before anything is written, so a failing generator
    cannot leave the tree half-rendered.
    """
    changed = []
    for path, text in _rendered().items():
        if path.read_text() != text:
            path.write_text(text)
            changed.append(path)
    return changed


def check() -> list[str]:
    """Error strings for every configured file that is stale."""
    errors = []
    for path, fresh in _rendered().items():
        current = path.read_text()
        if current == fresh:
            continue
        name = str(path.relative_to(REPO_ROOT))
        diff = difflib.unified_diff(
            current.splitlines(),
            fresh.splitlines(),
            f'{name} (current)',
            f'{name} (regenerated)',
            lineterm='',
            n=0,
        )
        errors.append('\n'.join([f'{name}: stale rendered values', *diff]))
    return errors


def publish(text: str, namespace: dict, fname: str = '<src>') -> str:
    """Marker- and generator-free text, validated before it can ship.

    cog only checks that generators ran; it does not know notebook cells
    exist. The failure that matters here is structural -- output landing
    outside its cell, or half a markdown line losing its comment prefix --
    so the stripped text must parse to the same cell shape as its source
    and survive a jupytext round trip byte-identically.
    """
    stripped = _run(text, namespace, fname, delete_code=True)
    if MARKERS[0] in stripped or MARKERS[2] in stripped:
        raise PublishError(f'error: {fname}: marker residue survived the strip')
    before = jupytext.reads(text, fmt='py:percent')
    after = jupytext.reads(stripped, fmt='py:percent')
    shape = [(c.cell_type, bool(c.source.strip())) for c in before.cells]
    if shape != [(c.cell_type, bool(c.source.strip())) for c in after.cells]:
        raise PublishError(
            f'error: {fname}: cell structure changed during strip '
            f'({len(before.cells)} cells -> {len(after.cells)})',
        )
    if jupytext.writes(after, fmt='py:percent') != stripped:
        raise PublishError(
            f'error: {fname}: stripped text is not a jupytext fixed point -- '
            'a generator likely emitted a line without its comment prefix',
        )
    return stripped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help="report files whose rendered values are stale; don't write",
    )
    args = parser.parse_args()
    try:
        if args.check:
            errors = check()
            for error in errors:
                print(error, file=sys.stderr)
            return 1 if errors else 0
        for path in apply():
            print(f'rendered {path.relative_to(REPO_ROOT)}', file=sys.stderr)
        return 0
    except ScriptError as e:
        raise SystemExit(str(e)) from e


if __name__ == '__main__':
    sys.exit(main())
