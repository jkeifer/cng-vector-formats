#!/usr/bin/env python3
"""Build the published workshop tree.

The `workshop` branch is a pure build artifact: every file on it is
reproducible from `main`. This assembles that tree -- repo files named by
[tool.workshop-build] include, the static/ overlay, generated notebooks and
notes, and a derived pyproject/lock -- into the workshop worktree.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tables that participants need. Everything else in main's pyproject is
# authoring machinery: dev dependencies, lint config, the scrubber's file
# map, the recorded workshop location.
KEEP_TABLES = ('project', 'tool.uv')


def derive_pyproject(text: str) -> str:
    """main's pyproject with the authoring machinery stripped out."""
    kept: list[str] = []
    keeping = True
    for line in text.splitlines(keepends=True):
        header = re.match(r'^\[+([^\]]+)\]+', line)
        if header:
            table = header.group(1)
            keeping = any(
                table == name or table.startswith(f'{name}.') for name in KEEP_TABLES
            )
        if keeping:
            kept.append(line)
    return ''.join(kept)


def write_deps(repo: Path, staging: Path) -> None:
    """Write the workshop's pyproject.toml and uv.lock into staging.

    The lock is seeded from the repo's own lock and re-resolved offline, so
    it is a derivation of that lock rather than an independent resolution:
    participants get exactly the versions contributors develop against, and
    the build needs no network.
    """
    (staging / 'pyproject.toml').write_text(
        derive_pyproject((repo / 'pyproject.toml').read_text()),
    )
    shutil.copyfile(repo / 'uv.lock', staging / 'uv.lock')
    subprocess.run(
        ['uv', 'lock', '--offline'],
        cwd=staging,
        check=True,
        capture_output=True,
    )


def load_include(pyproject: Path) -> tuple[str, ...]:
    """Repo paths that ship to participants unchanged."""
    with pyproject.open('rb') as f:
        data = tomllib.load(f)
    include = data.get('tool', {}).get('workshop-build', {}).get('include', [])
    if not isinstance(include, list) or not all(isinstance(i, str) for i in include):
        raise SystemExit(
            'error: [tool.workshop-build] include must be a list of strings',
        )
    return tuple(include)


def _copy(source: Path, dest: Path) -> list[Path]:
    """Copy a file or directory tree, returning the files written.

    The return value is derived from the source, never from a glob of the
    destination. copytree(dirs_exist_ok=True) merges rather than replaces,
    so on a rebuild into a reused worktree a destination glob would report
    files this build never wrote -- hiding stale leftovers from the caller's
    cruft check instead of flagging them.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest, dirs_exist_ok=True)
        return [
            dest / p.relative_to(source)
            for p in sorted(source.rglob('*'))
            if p.is_file()
        ]
    shutil.copyfile(source, dest)
    return [dest]


def _generated(staging: Path) -> list[Path]:
    """The notebooks and notes the generation step wrote, per the config.

    Read from the scrubber config -- the authority on what gets generated --
    rather than by globbing staging/notebooks and staging/notes, for the
    same reason as _copy: a reused worktree's leftovers must not be counted
    as written. A renamed exercise is exactly the case that matters, and
    renamed exercises live in notebooks/.
    """
    import generate_notebooks

    from ipynb_scrubber.config import ProjectConfig

    config = ProjectConfig.from_file(generate_notebooks.PYPROJECT)
    written: list[Path] = []
    for configured in config.files:
        entry = generate_notebooks._rebase(configured, staging)
        # The completed and exercise notebooks are written unconditionally.
        written += [entry.input, entry.output]
        # The notes file is written only when the notebook has note-tagged
        # cells. Notebook 03 declares a notes-file and produces none, so
        # trusting the config here would report a file that was never
        # written -- the same error as globbing, in reverse.
        if entry.notes_file is not None and entry.notes_file.is_file():
            written.append(entry.notes_file)
    return written


def build(repo: Path, staging: Path) -> set[Path]:
    """Assemble the complete published tree. Returns paths relative to staging."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import generate_notebooks

    staging.mkdir(parents=True, exist_ok=True)
    # generate_notebooks resolves its output dir, so the paths _generated
    # derives are resolved; match that here or relative_to below fails.
    staging = staging.resolve()
    written: list[Path] = []

    for name in load_include(repo / 'pyproject.toml'):
        source = repo / name
        if not source.exists():
            raise SystemExit(f'error: include entry {name!r} does not exist')
        written += _copy(source, staging / name)

    static_dir = repo / 'static'
    for source in sorted(p for p in static_dir.rglob('*') if p.is_file()):
        written += _copy(source, staging / source.relative_to(static_dir))

    for source in sorted(
        p for p in (repo / 'notebooks' / 'assets').rglob('*') if p.is_file()
    ):
        written += _copy(source, staging / 'notebooks' / 'assets' / source.name)

    generate_notebooks.generate(staging)
    # Bookkeeping stays a separate step after generate() rather than being
    # folded into it: _generated checks which notes files actually landed on
    # disk, which only has an answer once generation has run.
    written += _generated(staging)

    write_deps(repo, staging)
    written += [staging / 'pyproject.toml', staging / 'uv.lock']

    return {p.relative_to(staging) for p in written}
