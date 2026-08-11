"""Assemble the published workshop tree and publish it into a worktree.

The publish branch is a pure build artifact: every file on it is reproducible
from the source branch. This module assembles that tree -- repo files named by
`config.build.include`, the optional static/ overlay, the context's declared
assets, the generated notebooks and notes, and a derived pyproject/lock -- and
publishes it into the worktree, with a guard against clobbering unpublished
work and a cruft report for tracked files no build wrote.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from pathlib import Path

import tomlkit

from workshopify import notebooks
from workshopify.config import Config
from workshopify.context import Context
from workshopify.errors import WorkshopifyError
from workshopify.git import git


def derive_pyproject(text: str, keep: tuple[str, ...], drop: tuple[str, ...]) -> str:
    """The repo's pyproject with the authoring machinery stripped out.

    tomlkit rather than a tomllib/tomli-w round trip so the comments that make
    the published pyproject readable survive. `keep` names the top-level
    tables (or `parent.child` pairs) that ship; `drop` then removes exact
    dotted keys from what was kept -- the workspace wiring under [tool.uv]
    must not reach participants, who have no workshopify checkout to point at.
    """
    doc = tomlkit.parse(text)

    kept_children: dict[str, set[str] | None] = {}
    for name in keep:
        head, _, child = name.partition('.')
        if not child:
            kept_children[head] = None
        elif kept_children.get(head, set()) is not None:
            kept_children.setdefault(head, set()).add(child)

    for key in list(doc.keys()):
        children = kept_children.get(key, ...)
        if children is ...:
            del doc[key]
        elif children is not None:
            table = doc[key]
            for child in list(table.keys()):
                if child not in children:
                    del table[child]

    for dotted in drop:
        node = doc
        *parents, last = dotted.split('.')
        for part in parents:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None and last in node:
            del node[last]

    return tomlkit.dumps(doc)


def write_deps(config: Config, staging: Path) -> None:
    """Write the workshop's pyproject.toml and uv.lock into staging.

    The lock is seeded from the repo's own lock and re-resolved offline, so
    it is a derivation of that lock rather than an independent resolution:
    participants get exactly the versions contributors develop against, and
    the build needs no network.
    """
    (staging / 'pyproject.toml').write_text(
        derive_pyproject(
            config.pyproject.read_text(),
            config.build.keep_tables,
            config.build.drop_keys,
        ),
    )
    shutil.copyfile(config.root / 'uv.lock', staging / 'uv.lock')
    try:
        subprocess.run(
            ['uv', 'lock', '--offline'],
            cwd=staging,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise WorkshopifyError(
            f'error: uv lock --offline failed in {staging}:\n{e.stderr}',
        ) from e


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


def _rebase_asset(target: Path, root: Path, staging: Path) -> Path:
    """Where an asset target lands under staging.

    Asset targets are absolute paths under the repo root; rebasing them under
    staging means relative_to(root). A target outside root is a config error,
    diagnosed here rather than letting relative_to's bare ValueError escape.
    """
    try:
        return staging / target.relative_to(root)
    except ValueError as e:
        raise WorkshopifyError(
            f'error: asset target {target} is outside the repo root {root}',
        ) from e


def build(config: Config, ctx: Context, staging: Path) -> set[Path]:
    """Assemble the complete published tree. Returns paths relative to staging."""
    staging.mkdir(parents=True, exist_ok=True)
    # notebooks.generate resolves its output dir, so the paths it reports back
    # are resolved; match that here or relative_to below fails.
    staging = staging.resolve()
    written: list[Path] = []

    for name in config.build.include:
        source = config.root / name
        if not source.exists():
            raise WorkshopifyError(f'error: include entry {name!r} does not exist')
        written += _copy(source, staging / name)

    static_dir = config.root / 'static'
    if static_dir.is_dir():
        for source in sorted(p for p in static_dir.rglob('*') if p.is_file()):
            written += _copy(source, staging / source.relative_to(static_dir))

    for target, source in sorted(ctx.assets.items()):
        written += _copy(source, _rebase_asset(target, config.root, staging))

    written += notebooks.generate(config, ctx, staging)

    write_deps(config, staging)
    written += [staging / 'pyproject.toml', staging / 'uv.lock']

    return {p.relative_to(staging) for p in written}


def is_dirty(worktree: Path) -> bool:
    """True if the worktree has uncommitted changes, tracked or untracked."""
    return bool(git(worktree, 'status', '--porcelain').strip())


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
        Path(name) for name in git(worktree, 'ls-files', '-z').split('\0') if name
    }
    return sorted(tracked - written)


def clean(worktree: Path) -> None:
    """Remove every tracked file. Ignored files survive deliberately.

    git rm rather than rm -rf, so git decides what is removable -- and any
    large ignored cache under the worktree is not refetched.

    -f because git rm refuses a file with local modifications otherwise. This
    is only reachable in two states: the dirty guard passed, so the worktree
    is clean and -f changes nothing; or the user passed --overwrite-dirty,
    which authorises losing uncommitted worktree changes -- exactly what -f
    does. Forcing is correct in both, not a workaround for the error.
    """
    git(worktree, 'rm', '-r', '-f', '--quiet', '--ignore-unmatch', '.')


def publish_into(
    config: Config,
    ctx: Context,
    target: Path,
    *,
    clean_first: bool,
    overwrite_dirty: bool,
) -> int:
    """The publish itself: guard, clean, build, then report cruft.

    Reports every failure -- its own guard's, and those of the steps it calls
    -- as a WorkshopifyError. The CLI is the boundary that decides what one
    costs; this layer never exits.
    """
    if is_dirty(target) and not overwrite_dirty:
        raise WorkshopifyError(
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

    written = build(config, ctx, target)

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
