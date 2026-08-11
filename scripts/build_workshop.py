#!/usr/bin/env python3
"""Build the published workshop tree.

The `workshop` branch is a pure build artifact: every file on it is
reproducible from `main`. This assembles that tree -- repo files named by
[tool.workshop-build] include, the static/ overlay, generated notebooks and
notes, and a derived pyproject/lock -- into the workshop worktree.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib

from pathlib import Path

import generate_notebooks
import worktree

from common import REPO_ROOT, ScriptError

# Tables that participants need. Everything else in main's pyproject is
# authoring machinery: dev dependencies, lint config, the scrubber's file
# map, the recorded workshop location.
KEEP_TABLES = ('project', 'tool.uv')


def derive_pyproject(text: str) -> str:
    """main's pyproject with the authoring machinery stripped out.

    Line-based rather than a tomllib/tomli-w round trip, which would drop the
    comments that make the published pyproject readable. The cost is a
    dependency on an invariant TOML does not guarantee: no line inside a
    multi-line ('''...''') string may begin with `[`, or it reads here as a
    table header and either truncates a kept table mid-string or resumes
    keeping in the middle of a dropped one. pyproject.toml has no multi-line
    strings today -- but locations/*.toml uses them heavily -- so rather than
    leave that holding by luck, the derived text is parsed back and checked.
    """
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
    derived = ''.join(kept)

    allowed = {name.split('.', 1)[0] for name in KEEP_TABLES}
    try:
        leaked = sorted(set(tomllib.loads(derived)) - allowed)
    except tomllib.TOMLDecodeError as e:
        raise ScriptError(f'error: derived pyproject.toml does not parse: {e}') from e
    if leaked:
        raise ScriptError(f'error: derived pyproject.toml kept extra tables: {leaked}')
    return derived


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
    try:
        subprocess.run(
            ['uv', 'lock', '--offline'],
            cwd=staging,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ScriptError(
            f'error: uv lock --offline failed in {staging}:\n{e.stderr}',
        ) from e


def load_include(pyproject: Path) -> tuple[str, ...]:
    """Repo paths that ship to participants unchanged."""
    with pyproject.open('rb') as f:
        data = tomllib.load(f)
    include = data.get('tool', {}).get('workshop-build', {}).get('include', [])
    if not isinstance(include, list) or not all(isinstance(i, str) for i in include):
        raise ScriptError(
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


def build(repo: Path, staging: Path) -> set[Path]:
    """Assemble the complete published tree. Returns paths relative to staging."""
    staging.mkdir(parents=True, exist_ok=True)
    # generate_notebooks resolves its output dir, so the paths it reports back
    # are resolved; match that here or relative_to below fails.
    staging = staging.resolve()
    written: list[Path] = []

    for name in load_include(repo / 'pyproject.toml'):
        source = repo / name
        if not source.exists():
            raise ScriptError(f'error: include entry {name!r} does not exist')
        written += _copy(source, staging / name)

    static_dir = repo / 'static'
    for source in sorted(p for p in static_dir.rglob('*') if p.is_file()):
        written += _copy(source, staging / source.relative_to(static_dir))

    written += generate_notebooks.generate(staging)

    write_deps(repo, staging)
    written += [staging / 'pyproject.toml', staging / 'uv.lock']

    return {p.relative_to(staging) for p in written}


def _git(worktree: Path, *args: str) -> str:
    """Run git in worktree, surfacing its diagnostic if it fails.

    check=True with capture_output throws git's explanation away and leaves
    the user a bare "returned non-zero exit status 1", so the stderr git went
    to the trouble of writing is re-raised as the error message.
    """
    try:
        return subprocess.run(
            ['git', '-C', str(worktree), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        raise ScriptError(
            f'error: git {" ".join(args)} failed in {worktree}:\n{e.stderr}',
        ) from e


def is_dirty(worktree: Path) -> bool:
    """True if the worktree has uncommitted changes, tracked or untracked."""
    return bool(_git(worktree, 'status', '--porcelain').strip())


def unwritten(worktree: Path, written: set[Path]) -> list[Path]:
    """Tracked files this build did not write.

    A stale tracked file shows in `git status` as nothing at all, because it
    is unchanged -- so without this, a renamed exercise leaves its old file on
    the branch and it ships silently.

    -z because with the default core.quotePath a non-ASCII path comes back
    quoted and backslash-escaped ("sub/caf\\303\\251.txt"), which can never
    match a Path from build() -- it would be reported as cruft forever, and
    --clean could never resolve it.
    """
    tracked = {
        Path(name) for name in _git(worktree, 'ls-files', '-z').split('\0') if name
    }
    return sorted(tracked - written)


def clean(worktree: Path) -> None:
    """Remove every tracked file. Ignored files survive deliberately.

    git rm rather than rm -rf, so git decides what is removable -- and the
    multi-gigabyte .hctef-cache under the worktree is not refetched.

    -f because git rm refuses a file with local modifications otherwise. This
    is only reachable in two states: the dirty guard passed, so the worktree
    is clean and -f changes nothing; or the user passed --overwrite-dirty,
    which authorises losing uncommitted worktree changes -- exactly what -f
    does. Forcing is correct in both, not a workaround for the error.
    """
    _git(worktree, 'rm', '-r', '-f', '--quiet', '--ignore-unmatch', '.')


def _build_into(target: Path, *, clean_first: bool, overwrite_dirty: bool) -> int:
    """The publish itself: guard, clean, build, then report cruft.

    Reports every failure -- its own guard's, and those of the steps it calls
    -- as a ScriptError. `run` below is the boundary that decides what one
    costs.
    """
    if is_dirty(target) and not overwrite_dirty:
        raise ScriptError(
            f'error: {target} has uncommitted changes.\n'
            '  They may be an unpublished build, or notebook edits made in '
            'Jupyter that are not yet synced back to src/.\n'
            '  Commit them, or re-run with --overwrite-dirty: the build then '
            'overwrites\n'
            '  any dirty file it writes and leaves the rest, and --clean '
            'additionally\n'
            '  deletes every tracked file, modifications included.',
        )

    if clean_first:
        clean(target)

    written = build(REPO_ROOT, target)

    print(f'built into {target}', file=sys.stderr)
    print(f'review with: git -C {target} status', file=sys.stderr)
    print('publish with:', file=sys.stderr)
    print(f'  git -C {target} add -A', file=sys.stderr)
    print(
        f'  PREK_ALLOW_NO_CONFIG=1 git -C {target} commit -m "Update notebooks"',
        file=sys.stderr,
    )
    print(f'  git -C {target} push', file=sys.stderr)
    print(
        'PREK_ALLOW_NO_CONFIG=1 is required: git hooks are shared across all '
        'worktrees,\n'
        'and the workshop branch intentionally carries no pre-commit config.',
        file=sys.stderr,
    )

    # Printed last, after the success output above, so the one failure this
    # report exists to catch -- a renamed exercise shipping silently -- does
    # not scroll off above the happy path.
    stale = unwritten(target, written)
    if stale:
        print('not written by this build:', file=sys.stderr)
        for path in stale:
            print(f'  {path}', file=sys.stderr)
        print('re-run with --clean to remove', file=sys.stderr)

    return 0


def run(target: Path, *, clean_first: bool, overwrite_dirty: bool) -> int:
    """Build into an already-resolved worktree. Returns an exit status.

    Split from main() so the guard can be tested against a throwaway repo:
    main() resolves the real workshop worktree, and a test reaching that
    would rebuild -- or with --clean, delete -- the developer's own.

    This is the outermost entry point a build goes through -- main() adds only
    argument parsing and the worktree -- so it is where a diagnosed failure
    becomes an exit status, and the steps below it stay callable by anything
    that would rather handle one than die.
    """
    try:
        return _build_into(
            target,
            clean_first=clean_first,
            overwrite_dirty=overwrite_dirty,
        )
    except ScriptError as e:
        raise SystemExit(str(e)) from e


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--clean',
        action='store_true',
        help='remove all tracked files from the worktree before building',
    )
    parser.add_argument(
        '--overwrite-dirty',
        action='store_true',
        help='proceed even though the worktree has uncommitted changes',
    )
    args = parser.parse_args()

    # Only the worktree needs wrapping here: `run` already converts everything
    # the build itself can raise.
    try:
        target = worktree.prepare_worktree(
            'workshop',
            REPO_ROOT / 'workshop',
            orphan=False,
        )
    except ScriptError as e:
        raise SystemExit(str(e)) from e

    return run(target, clean_first=args.clean, overwrite_dirty=args.overwrite_dirty)


if __name__ == '__main__':
    sys.exit(main())
