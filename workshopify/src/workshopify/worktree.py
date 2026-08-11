"""Prepare a git worktree for a branch, creating the branch if needed.

Generic worktree lifecycle helper: given a branch name and a path, this ensures
the branch exists and is checked out as a git worktree, then returns the
worktree path. It does *not* run any generation or commit anything -- compose it
with whatever produces content into the worktree, review the result, and commit
yourself.
"""

from __future__ import annotations

import sys

from pathlib import Path

from workshopify.errors import WorkshopifyError
from workshopify.git import git, succeeds


def _branch_exists(root: Path, branch: str) -> bool:
    return succeeds(root, 'show-ref', '--verify', '--quiet', f'refs/heads/{branch}')


def _remotes_with_branch(root: Path, branch: str) -> list[str]:
    """Remotes that have a tracking ref for `branch`, e.g. ['origin'].

    A fresh clone has no local branch, only `origin/<branch>`. Without this the
    branch looks nonexistent and we would branch off HEAD instead -- quietly
    producing a worktree with the wrong content.
    """
    refs = git(
        root,
        'for-each-ref',
        '--format=%(refname)',
        f'refs/remotes/*/{branch}',
    )
    return [
        ref[len('refs/remotes/') :].removesuffix(f'/{branch}')
        for ref in refs.splitlines()
        if ref
    ]


def _worktrees(root: Path) -> dict[Path, str]:
    """Map each worktree path -> its checked-out branch (bare-checkout aside)."""
    result: dict[Path, str] = {}
    current: Path | None = None
    for line in git(root, 'worktree', 'list', '--porcelain').splitlines():
        if line.startswith('worktree '):
            current = Path(line[len('worktree ') :]).resolve()
        elif line.startswith('branch ') and current is not None:
            # e.g. "branch refs/heads/workshop"
            result[current] = line[len('branch ') :].removeprefix('refs/heads/')
    return result


def prepare_worktree(root: Path, branch: str, path: Path, orphan: bool) -> Path:
    path = path.resolve()

    # Prune stale registrations (e.g. a worktree dir that was deleted) so we
    # don't trip over "branch already used by worktree" for a gone location.
    git(root, 'worktree', 'prune')

    worktrees = _worktrees(root)

    # A branch can only be checked out in one worktree. If it already is, reuse
    # that -- but insist it matches the requested path to avoid surprises.
    for existing_path, existing_branch in worktrees.items():
        if existing_branch == branch:
            if existing_path != path:
                raise WorkshopifyError(
                    f'error: branch {branch!r} is already checked out at '
                    f'{existing_path} (requested {path}). Reuse that path or '
                    f'remove it with `git worktree remove`.',
                )
            return path

    # Nothing checked out `branch` yet. The target path must be free.
    if path in worktrees:
        raise WorkshopifyError(
            f'error: {path} is already a worktree for branch '
            f'{worktrees[path]!r}, not {branch!r}',
        )
    if path.exists() and any(path.iterdir()):
        raise WorkshopifyError(f'error: {path} exists and is not empty')

    if _branch_exists(root, branch):
        git(root, 'worktree', 'add', str(path), branch)
        return path

    # No local branch. Before inventing one, check whether it already exists on
    # a remote -- on a fresh clone that is the normal case.
    remotes = _remotes_with_branch(root, branch)
    if len(remotes) > 1:
        raise WorkshopifyError(
            f'error: branch {branch!r} exists on multiple remotes '
            f'({", ".join(sorted(remotes))}) and no local branch resolves the '
            f'ambiguity. Create it locally first, e.g. `git branch {branch} '
            f'{min(remotes)}/{branch}`.',
        )
    if remotes:
        remote = remotes[0]
        print(f'creating {branch!r} tracking {remote}/{branch}', file=sys.stderr)
        git(
            root,
            'worktree',
            'add',
            '--track',
            '-b',
            branch,
            str(path),
            f'{remote}/{branch}',
        )
    elif orphan:
        # New orphan branch (no shared history) materialized in the worktree.
        git(root, 'worktree', 'add', '--orphan', '-b', branch, str(path))
    else:
        # Genuinely new branch off the current HEAD. Say so -- if the user meant
        # to check out an existing remote branch, this is where it goes wrong.
        head = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').strip()
        print(
            f'note: no local or remote branch {branch!r}; creating it from {head}',
            file=sys.stderr,
        )
        git(root, 'worktree', 'add', '-b', branch, str(path))

    return path
