#!/usr/bin/env python3
"""Generate the completed + exercise notebooks (and notes) from the src/ files.

The py:percent files in src/ are the source of truth. This script:

  1. Renders each src/NN_<name>.py to a completed .ipynb under
     notebooks/completed/ via Jupytext.
  2. Runs ipynb-scrubber over each completed notebook to produce the exercise
     notebook (notebooks/NN_<name>.ipynb) + notes file (notes/NN_<name>.md).

Both steps write into --output-dir, which is the directory that *contains* the
`notebooks/` and `notes/` subdirectories. It defaults to the repo root (`.`), so
a bare run regenerates the repo's own notebooks in place. Point it at a
worktree to stage a dist branch, e.g.:

    uv run scripts/worktree.py workshop            # -> ./workshop
    uv run scripts/generate_notebooks.py --output-dir ./workshop

Filenames, tags, and clear-text are read from the [tool.ipynb-scrubber] config
in pyproject.toml, so this stays single-sourced with the local `scrub-project`
workflow. We drive the scrubber through its Python API with each config entry's
paths rebased under --output-dir, which is what `scrub-project` itself does
internally -- so the output is identical, without a rewritten temp config.

Two lists in [tool.generate-notebooks] describe the paths under the managed
trees that are inputs rather than generated output:

    [tool.generate-notebooks]
    keep = ["notebooks/assets"]   # --prune must not delete these
    copy = ["notebooks/assets"]   # copy these into a non-local --output-dir

Both are optional; a project that sets neither behaves as if they were empty.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib

from dataclasses import replace
from pathlib import Path

from ipynb_scrubber.config import FileEntry, ProjectConfig, ScrubbingOptions
from ipynb_scrubber.exceptions import ScrubberError
from ipynb_scrubber.processor import process_notebook, write_notes_file

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / 'src'
PYPROJECT = REPO_ROOT / 'pyproject.toml'

# Distinct from 1 (errors) and 2 (argparse usage) so a caller can tell "the tree
# has drifted" apart from "the run failed": generation still succeeded.
EXIT_STALE = 3


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


def _entry_paths(entry: FileEntry) -> tuple[Path, ...]:
    """Every path one config entry owns."""
    paths = (entry.input, entry.output, entry.notes_file)
    return tuple(p for p in paths if p is not None)


def _load_paths(pyproject: Path, key: str) -> tuple[str, ...]:
    """One [tool.generate-notebooks] list of paths under the managed trees.

    These name inputs rather than generated output. Assets are the motivating
    case: nothing in the scrubber config claims notebooks/assets/, so without
    `keep` --prune deletes the screenshots, and without `copy` a stale copy of
    them survives forever in a published worktree.
    """
    with pyproject.open('rb') as f:
        data = tomllib.load(f)

    paths = data.get('tool', {}).get('generate-notebooks', {}).get(key, [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise SystemExit(
            f'error: [tool.generate-notebooks] {key} must be a list of strings',
        )
    return tuple(paths)


def _unmatched(paths: tuple[str, ...], base: Path, roots: set[str]) -> list[str]:
    """Entries that name nothing under the managed trees.

    A typo is otherwise silent and undoes the point of the setting: `keep =
    ["notebook/assets"]` puts the assets straight back on the stale list, where
    --prune deletes them.
    """
    return [
        entry
        for entry in paths
        if not Path(entry).parts
        or Path(entry).parts[0] not in roots
        or not (base / entry).exists()
    ]


def _warn_unmatched(
    key: str,
    paths: tuple[str, ...],
    base: Path,
    roots: set[str],
) -> None:
    """Report, without failing: an empty managed directory is legitimate."""
    for entry in _unmatched(paths, base, roots):
        print(
            f'warning: [tool.generate-notebooks] {key} entry {entry!r} matches '
            f'nothing under {", ".join(sorted(roots))} in {base}',
            file=sys.stderr,
        )


def _copy_inputs(paths: tuple[str, ...], output_dir: Path) -> None:
    """Copy each `copy` path from the repo into a separate output dir.

    Generation only writes what the scrubber config claims, so an input living
    under a managed tree (an image the notebooks embed, say) never reaches a
    published worktree after the first time it is committed there -- and since
    the worktree keeps its stale copy, `git status` shows nothing to signal it.
    Copying overwrites, so the worktree tracks whatever the repo now holds.

    A no-op when the output dir is the repo itself: source and destination are
    the same file.
    """
    if output_dir == REPO_ROOT:
        return

    for entry in paths:
        source = REPO_ROOT / entry
        if not source.exists():
            continue  # already warned about
        dest = output_dir / entry
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
        print(f'copied {entry}', file=sys.stderr)


def _stale_paths(
    entries: list[FileEntry],
    output_dir: Path,
    roots: set[str],
    keep: tuple[str, ...] = (),
) -> list[Path]:
    """Files under the managed trees that the config doesn't claim.

    Everything below notebooks/ and notes/ is generated, so a file we aren't
    about to write is a leftover from an older config -- a renamed notebook, or
    a notes-file for a notebook that no longer has any notes. Nothing removes
    those otherwise, and when the output dir is a published worktree they ship.

    `keep` carves out the exceptions: paths that live under those trees but are
    inputs rather than output.
    """
    expected = {p.resolve() for entry in entries for p in _entry_paths(entry)}
    kept = [(output_dir / k).resolve() for k in keep]

    def is_kept(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == k or k in resolved.parents for k in kept)

    return [
        path
        for root in sorted(roots)
        if (output_dir / root).is_dir()
        for path in sorted((output_dir / root).rglob('*'))
        if path.is_file() and path.resolve() not in expected and not is_kept(path)
    ]


def _prune_stale(stale: list[Path], output_dir: Path, roots: set[str]) -> None:
    """Delete stale files, and any directory the deletions leave empty.

    Pruning rather than wiping the tree is deliberate: `jupytext --update` needs
    the previous notebook to still be there to keep its cell ids stable.
    """
    for path in stale:
        path.unlink()
        print(f'removed stale {path.relative_to(output_dir)}', file=sys.stderr)

    for root in sorted(roots):
        base = output_dir / root
        if not base.is_dir():
            continue
        # Deepest first, so a directory emptied by its children's removal goes too.
        for path in sorted(base.rglob('*'), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()


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


def _scrub(entry: FileEntry, options: ScrubbingOptions) -> None:
    """Completed notebook -> exercise notebook (+ notes), via the scrubber API."""
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


def generate(output_dir: Path, prune: bool = False) -> bool:
    """Generate the notebooks. Returns True if stale output was left in place."""
    output_dir = output_dir.resolve()
    try:
        config = ProjectConfig.from_file(PYPROJECT)
    except ScrubberError as e:
        raise SystemExit(f'error: {e}') from e

    # The top-level directory of each configured path (notebooks/, notes/) is a
    # tree we own end to end, so we get to say what does and doesn't belong.
    roots = {
        p.parts[0]
        for configured in config.files
        for p in _entry_paths(configured)
        if not p.is_absolute() and p.parts
    }
    entries = [_rebase(configured, output_dir) for configured in config.files]

    keep = _load_paths(PYPROJECT, 'keep')
    copy = _load_paths(PYPROJECT, 'copy')
    _warn_unmatched('keep', keep, output_dir, roots)
    _warn_unmatched('copy', copy, REPO_ROOT, roots)

    stale = _stale_paths(entries, output_dir, roots, keep)
    if stale and prune:
        _prune_stale(stale, output_dir, roots)
        stale = []
    elif stale:
        # Deleting is opt-in: report, and say how to act on it.
        for path in stale:
            print(f'stale {path.relative_to(output_dir)}', file=sys.stderr)
        print(
            f'{len(stale)} stale file(s) the config no longer claims; '
            're-run with --prune to delete them',
            file=sys.stderr,
        )

    # After pruning, so a copied input that is not also in `keep` survives the
    # run rather than being deleted and rewritten in the same breath.
    _copy_inputs(copy, output_dir)

    for entry in entries:
        _render_completed(entry.input)
        _scrub(entry, entry.get_options(config.global_options))

    return bool(stale)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=REPO_ROOT,
        help='directory containing notebooks/ and notes/ (default: repo root)',
    )
    parser.add_argument(
        '--prune',
        action='store_true',
        help='delete generated files the config no longer claims; without it '
        f'they are only reported, and the run exits {EXIT_STALE}',
    )
    args = parser.parse_args()
    stale = generate(args.output_dir, prune=args.prune)
    return EXIT_STALE if stale else 0


if __name__ == '__main__':
    sys.exit(main())
