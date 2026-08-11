"""One git helper for the whole package, surfacing git's own diagnostics.

`check=True` with `capture_output` throws git's explanation away and leaves
the user a bare "returned non-zero exit status 1"; the stderr git went to the
trouble of writing is re-raised as the error message instead. This helper was
previously duplicated across two scripts with divergent behavior -- one path
gave diagnostics, the other a raw traceback.
"""

from __future__ import annotations

import subprocess

from pathlib import Path

from workshopify.errors import WorkshopifyError


def git(cwd: Path, *args: str) -> str:
    """Run git in cwd, returning stdout; a failure names the command and stderr."""
    try:
        return subprocess.run(
            ['git', '-C', str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        raise WorkshopifyError(
            f'error: git {" ".join(args)} failed in {cwd}:\n{e.stderr}',
        ) from e


def succeeds(cwd: Path, *args: str) -> bool:
    """Whether the command exits 0. For probes where failure is an answer."""
    return (
        subprocess.run(
            ['git', '-C', str(cwd), *args],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
