"""Render cog-templated sources, entirely in memory.

The files named by [tool.workshopify.render] carry cog generators in
comments; the values those generators produce sit inline in the file, so the
sources read normally and re-rendering them is a no-op until the underlying
data changes. This module knows nothing about what the generators compute:
their namespace comes from the context module (via workshopify.context), so
the same machinery serves any repo that templates its sources this way.

    [tool.workshopify.render]
    files = ["src/*.py"]

Three operations, each taking the resolved Config and loaded Context:

    apply(config, ctx)      re-render every configured file and asset in place
    check(config, ctx)      error strings if any file or asset is stale
    publish(text, ns)       the text with markers and generators stripped,
                            validated as a sound py:percent document

Failures raise WorkshopifyError/PublishError; deciding to exit is the CLI's
job, never this module's.
"""

from __future__ import annotations

import difflib
import io
import shutil

from pathlib import Path

import jupytext

from cogapp import Cog

from workshopify.config import Config
from workshopify.context import Context
from workshopify.errors import WorkshopifyError

# HTML-comment forms of cog's markers, so a marker that ever leaked into
# rendered markdown would at least be invisible. One definition, used by
# every operation and stated in the docs -- do not vary per file.
MARKERS = ('<!--[[[cog', ']]]-->', '<!--[[[end]]]-->')

# `md()` emits generator output as markdown-cell comment lines. It is defined
# here, not in the context module, because it needs the `cog` object that
# cogapp injects into the generator namespace at run time.
PROLOGUE = "def md(o): cog.outl('\\n'.join('# ' + l for l in str(o).split('\\n')))"


class PublishError(WorkshopifyError):
    """Stripped output that is structurally unsound and must not ship."""


def _run(text: str, namespace: dict, fname: str, *, delete_code: bool) -> str:
    cog = Cog()
    options = cog.options
    options.begin_spec, options.end_spec, options.end_output = MARKERS
    options.prologue = PROLOGUE
    options.delete_code = delete_code
    out = io.StringIO()
    cog.process_file(io.StringIO(text), out, fname=fname, globals=dict(namespace))
    return out.getvalue()


def _files(config: Config) -> list[Path]:
    files = sorted(
        path for pattern in config.render.files for path in config.root.glob(pattern)
    )
    if not files:
        raise WorkshopifyError(
            f'error: [tool.workshopify.render] files matched nothing: '
            f'{list(config.render.files)}',
        )
    return files


def _rendered(config: Config, namespace: dict) -> dict[Path, str]:
    """Every configured file re-rendered, in memory, none written."""
    return {
        path: _run(path.read_text(), namespace, str(path), delete_code=False)
        for path in _files(config)
    }


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _asset_errors(config: Config, ctx: Context) -> list[str]:
    errors = []
    for target, source in sorted(ctx.assets.items()):
        name = _display(target, config.root)
        if not source.is_file():
            errors.append(f'{source}: missing; cannot check {name}')
        elif not target.is_file():
            errors.append(f'{name}: missing (expected a copy of {source})')
        elif target.read_bytes() != source.read_bytes():
            errors.append(f'{name}: does not match {source}')
    return errors


def apply(config: Config, ctx: Context) -> list[Path]:
    """Re-render every configured file and asset in place; what changed.

    Everything renders before anything is written -- and every asset source is
    verified to exist first -- so a failing generator or a missing screenshot
    cannot leave the tree half-rendered.
    """
    rendered = _rendered(config, ctx.namespace)
    missing = [str(s) for s in sorted(ctx.assets.values()) if not s.is_file()]
    if missing:
        raise WorkshopifyError(
            f'error: asset source(s) do not exist: {", ".join(missing)}',
        )
    changed = []
    for path, text in rendered.items():
        if path.read_text() != text:
            path.write_text(text)
            changed.append(path)
    for target, source in sorted(ctx.assets.items()):
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            changed.append(target)
    return changed


def check(config: Config, ctx: Context) -> list[str]:
    """Error strings for every stale rendered file and every wrong asset."""
    errors = []
    for path, fresh in _rendered(config, ctx.namespace).items():
        current = path.read_text()
        if current == fresh:
            continue
        name = _display(path, config.root)
        diff = difflib.unified_diff(
            current.splitlines(),
            fresh.splitlines(),
            f'{name} (current)',
            f'{name} (regenerated)',
            lineterm='',
            n=0,
        )
        errors.append('\n'.join([f'{name}: stale rendered values', *diff]))
    return errors + _asset_errors(config, ctx)


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
