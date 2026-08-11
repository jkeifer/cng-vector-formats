#!/usr/bin/env python3
"""Generate the completed + exercise notebooks (and notes) from the src/ files.

The py:percent files in src/ are the source of truth. This script:

  1. Renders each src/NN_<name>.py to a completed .ipynb under
     notebooks/completed/ via Jupytext.
  2. Runs ipynb-scrubber over each completed notebook to produce the exercise
     notebook (notebooks/NN_<name>.ipynb) + notes file (notes/NN_<name>.md).

Both steps write into --output-dir, which is the directory that *contains* the
`notebooks/` and `notes/` subdirectories. It defaults to the repo root (`.`), so
a bare run regenerates the repo's own notebooks in place. Point it at any other
directory to stage the generated files elsewhere, e.g.:

    uv run scripts/generate_notebooks.py --output-dir /path/to/somewhere

In this repo, notebook generation is one step of the full publish flow; see
`build_workshop.py` for assembling the complete published tree.

Filenames, tags, and clear-text are read from the [tool.ipynb-scrubber] config
in pyproject.toml, so this stays single-sourced with the local `scrub-project`
workflow. We drive the scrubber through its Python API with each config entry's
paths rebased under --output-dir, which is what `scrub-project` itself does
internally -- so the output is identical, without a rewritten temp config.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from dataclasses import replace
from pathlib import Path

from ipynb_scrubber.config import FileEntry, ProjectConfig, ScrubbingOptions
from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.processor import process_notebook, write_notes_file

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / 'src'
PYPROJECT = REPO_ROOT / 'pyproject.toml'


def _rebase(entry: FileEntry, output_dir: Path) -> FileEntry:
    """Repoint one config entry's paths at output_dir.

    Config paths are relative to the repo root; --output-dir may be a worktree.
    """
    return replace(
        entry,
        input=output_dir / entry.input,
        output=output_dir / entry.output,
        notes_file=output_dir / entry.notes_file if entry.notes_file else None,
    )


def _assign_cell_ids(path: Path) -> None:
    """Give every cell an id derived from its position.

    nbformat mints a random uuid4 per cell, so a plain render rewrites every
    cell of every notebook and a publish diff is pure churn. Deriving the id
    from the notebook stem and cell index makes the render a pure function of
    its source, with nothing to merge into.

    ensure_ascii=False because the notebooks carry non-ASCII -- a building
    name in kanji, em dashes in prose -- and escaping it would churn the diff
    just as badly as random ids did.
    """
    notebook = json.loads(path.read_text())
    for index, cell in enumerate(notebook['cells']):
        cell['id'] = f'{path.stem}-{index:03d}'
    path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + '\n')


def _render_completed(dest: Path) -> None:
    """Render src/<stem>.py -> dest via Jupytext.

    The scrubber input paths (e.g. notebooks/completed/01_<name>.ipynb) share
    their stem with the src/ file they are rendered from.
    """
    src_py = SRC_DIR / f'{dest.stem}.py'
    if not src_py.exists():
        raise SystemExit(f'error: missing source file {src_py}')

    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['jupytext', '--to', 'ipynb', '--output', str(dest), str(src_py)],
        check=True,
    )
    _assign_cell_ids(dest)


def _scrub(entry: FileEntry, options: ScrubbingOptions) -> bool:
    """Completed notebook -> exercise notebook (+ notes), via the scrubber API.

    Returns whether a notes file was written. This is the code that decides
    that -- a configured notes-file is only written when the notebook has
    note-tagged cells -- so it is the only place that can answer without
    re-deriving the answer from the filesystem afterwards.
    """
    notebook = json.loads(entry.input.read_text())
    processed, notes = process_notebook(notebook, options)

    if notes:
        if entry.notes_file is None:
            raise SystemExit(
                f'error: {entry.input} has {len(notes)} cell(s) tagged '
                f'"{options.note_tag}" but no notes-file is configured',
            )
        write_notes_file(notes, entry.notes_file)

    entry.output.parent.mkdir(parents=True, exist_ok=True)
    # indent=1 matches what `ipynb-scrubber scrub-project` writes. The rest
    # matches _assign_cell_ids: the exercise notebooks are published alongside
    # the completed ones, so escaping their non-ASCII churns the diff just as
    # badly.
    entry.output.write_text(json.dumps(processed, indent=1, ensure_ascii=False) + '\n')
    print(f'✓ {entry.input} → {entry.output}', file=sys.stderr)
    return bool(notes)


def generate(output_dir: Path) -> list[Path]:
    """Render every configured notebook into output_dir.

    Returns the absolute paths written, reported by the steps that wrote them
    rather than by globbing output_dir. build_workshop subtracts this from the
    published branch's tracked files to flag cruft, and output_dir may be a
    worktree a previous build already wrote into: a glob would count those
    leftovers as written, so a renamed exercise would keep shipping its old
    file, silently. In the other direction, a notes file is only written when
    the notebook has note-tagged cells -- notebook 03 declares one and produces
    none -- so the config alone would name a file that does not exist.
    """
    output_dir = output_dir.resolve()
    try:
        config = ProjectConfig.from_file(PYPROJECT)
    except ScrubberError as e:
        raise SystemExit(f'error: {e}') from e

    written: list[Path] = []
    for configured in config.files:
        entry = _rebase(configured, output_dir)
        _render_completed(entry.input)
        wrote_notes = _scrub(entry, entry.get_options(config.global_options))
        # The completed and exercise notebooks are written unconditionally.
        written += [entry.input, entry.output]
        if wrote_notes:
            written.append(entry.notes_file)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=REPO_ROOT,
        help='directory containing notebooks/ and notes/ (default: repo root)',
    )
    args = parser.parse_args()
    generate(args.output_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
