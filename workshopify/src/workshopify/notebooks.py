"""Generate the completed + exercise notebooks (and notes) from the src/ files.

The py:percent files in the notebooks source dir are the source of truth. For
each one, entirely in memory until the final write:

  1. Strip the embedded cog templating (render.publish), which also validates
     that the stripped text is a structurally sound py:percent document.
  2. Convert to a notebook via the jupytext API and give every cell an id
     derived from its position, writing the completed .ipynb under
     notebooks/completed/.
  3. Run ipynb-scrubber over the in-memory notebook to produce the exercise
     notebook (notebooks/NN_<name>.ipynb) + notes file (notes/NN_<name>.md).

All steps write into output_dir, which is the directory that *contains* the
`notebooks/` and `notes/` subdirectories. Point it at any directory to stage
the generated files there.

Filenames, tags, and clear-text are read from the [tool.ipynb-scrubber] config
in pyproject.toml, so this stays single-sourced with the local `scrub-project`
workflow. We drive the scrubber through its Python API with each config entry's
paths rebased under output_dir, which is what `scrub-project` itself does
internally -- so the output is identical, without a rewritten temp config.
"""

from __future__ import annotations

import json
import sys

from dataclasses import replace
from pathlib import Path

import jupytext

from ipynb_scrubber.config import FileEntry, ProjectConfig, ScrubbingOptions
from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.processor import process_notebook, write_notes_file
from jupytext.config import load_jupytext_configuration_file

from workshopify.config import Config
from workshopify.context import Context
from workshopify.errors import WorkshopifyError
from workshopify.render import publish


def _rebase(entry: FileEntry, output_dir: Path) -> FileEntry:
    """Repoint one config entry's paths at output_dir.

    Config paths are relative to the repo root; output_dir may be a worktree.
    """
    return replace(
        entry,
        input=output_dir / entry.input,
        output=output_dir / entry.output,
        notes_file=output_dir / entry.notes_file if entry.notes_file else None,
    )


def _dump(notebook: dict, dest: Path) -> None:
    """One convention for every .ipynb written: the completed and exercise
    notebooks are published side by side, so they must agree on it.

    ensure_ascii=False because the notebooks carry non-ASCII -- a building
    name in kanji, em dashes in prose -- and escaping it would churn every
    publish diff; indent=1 matches what `ipynb-scrubber scrub-project` writes.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + '\n')


def _render_completed(config: Config, ctx: Context, dest: Path) -> dict:
    """src/<stem>.py -> the completed notebook: written to dest and returned.

    Cell ids are derived from the notebook stem and cell index. nbformat mints
    a random uuid4 per cell, so without this a plain render rewrites every cell
    of every notebook and a publish diff is pure churn; positional ids make the
    render a pure function of its source, with nothing to merge into.
    """
    src_py = config.root / config.notebooks.src / f'{dest.stem}.py'
    if not src_py.exists():
        raise WorkshopifyError(f'error: missing source file {src_py}')

    published = publish(src_py.read_text(), ctx.namespace, str(src_py))
    # The [tool.jupytext] config must reach the API calls explicitly; only the
    # CLI discovers it. Without it the cell metadata filter that keeps
    # `raises-exception` tags falls back to defaults.
    jt_config = load_jupytext_configuration_file(str(config.pyproject))
    notebook = json.loads(
        jupytext.writes(
            jupytext.reads(published, fmt='py:percent', config=jt_config),
            fmt='ipynb',
            config=jt_config,
        ),
    )
    for index, cell in enumerate(notebook['cells']):
        cell['id'] = f'{dest.stem}-{index:03d}'
    _dump(notebook, dest)
    return notebook


def _scrub(notebook: dict, entry: FileEntry, options: ScrubbingOptions) -> bool:
    """Completed notebook -> exercise notebook (+ notes), via the scrubber API.

    Returns whether a notes file was written. This is the code that decides
    that -- a configured notes-file is only written when the notebook has
    note-tagged cells -- so it is the only place that can answer without
    re-deriving the answer from the filesystem afterwards.
    """
    processed, notes = process_notebook(notebook, options)

    if notes:
        if entry.notes_file is None:
            raise WorkshopifyError(
                f'error: {entry.input} has {len(notes)} cell(s) tagged '
                f'"{options.note_tag}" but no notes-file is configured',
            )
        write_notes_file(notes, entry.notes_file)

    _dump(processed, entry.output)
    print(f'✓ {entry.input} → {entry.output}', file=sys.stderr)
    return bool(notes)


def generate(config: Config, ctx: Context, output_dir: Path) -> list[Path]:
    """Render every configured notebook into output_dir.

    Returns the absolute paths written, reported by the steps that wrote them
    rather than by globbing output_dir. The build subtracts this from the
    published branch's tracked files to flag cruft, and output_dir may be a
    worktree a previous build already wrote into: a glob would count those
    leftovers as written, so a renamed exercise would keep shipping its old
    file, silently. In the other direction, a notes file is only written when
    the notebook has note-tagged cells -- a notebook may declare one and
    produce none -- so the config alone would name a file that does not exist.
    """
    output_dir = output_dir.resolve()
    try:
        project = ProjectConfig.from_file(config.pyproject)
    except ScrubberError as e:
        raise WorkshopifyError(f'error: {e}') from e

    written: list[Path] = []
    for configured in project.files:
        entry = _rebase(configured, output_dir)
        notebook = _render_completed(config, ctx, entry.input)
        wrote_notes = _scrub(notebook, entry, entry.get_options(project.global_options))
        # The completed and exercise notebooks are written unconditionally.
        written += [entry.input, entry.output]
        if wrote_notes:
            written.append(entry.notes_file)
    return written
