#!/usr/bin/env python3
"""Build the published workshop tree.

The `workshop` branch is a pure build artifact: every file on it is
reproducible from `main`. This assembles that tree -- repo files named by
[tool.workshop-build] include, the dist/ overlay, generated notebooks and
notes, and a derived pyproject/lock -- into the workshop worktree.
"""

from __future__ import annotations

import re
import shutil
import subprocess

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
