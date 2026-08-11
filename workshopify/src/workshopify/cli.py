"""The one command-line surface, and the one place a failure becomes an exit.

Every module below raises WorkshopifyError carrying the full diagnostic;
main() prints it to stderr and returns 1. Nothing else in the package may
exit the process.
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from workshopify import build, context, notebooks, params, render, worktree
from workshopify.config import Config
from workshopify.errors import WorkshopifyError


def _render(args: argparse.Namespace) -> int:
    config = Config.discover()
    changed = render.apply(config, context.load(config))
    for path in changed:
        print(f'rendered {_rel(path, config.root)}', file=sys.stderr)
    return 0


def _check(args: argparse.Namespace) -> int:
    config = Config.discover()
    errors = render.check(config, context.load(config))
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print('rendered values and assets are current', file=sys.stderr)
    return 0


def _generate(args: argparse.Namespace) -> int:
    config = Config.discover()
    written = notebooks.generate(
        config,
        context.load(config),
        args.output_dir or config.root,
    )
    for path in written:
        print(f'wrote {path}', file=sys.stderr)
    return 0


def _build(args: argparse.Namespace) -> int:
    config = Config.discover()
    target = worktree.prepare_worktree(
        config.root,
        config.build.branch,
        config.root / config.build.branch,
        orphan=False,
    )
    return build.publish_into(
        config,
        context.load(config),
        target,
        clean_first=args.clean,
        overwrite_dirty=args.overwrite_dirty,
    )


def _set(args: argparse.Namespace) -> int:
    config = Config.discover()
    changed = params.set_param(config.root, args.key, args.value)
    for path in changed:
        print(f'updated {_rel(path, config.root)}', file=sys.stderr)
    print(f'set {args.key} = {args.value!r}', file=sys.stderr)
    return 0


def _worktree(args: argparse.Namespace) -> int:
    config = Config.discover()
    path = args.path or config.root / args.branch
    print(worktree.prepare_worktree(config.root, args.branch, path, args.orphan))
    return 0


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='workshopify', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser(
        'render', help='re-render templated values and assets in place'
    ).set_defaults(func=_render)
    sub.add_parser(
        'check', help='report stale rendered values or assets; exit 1 if any'
    ).set_defaults(func=_check)

    generate = sub.add_parser(
        'generate', help='generate the notebooks and notes from src/'
    )
    generate.add_argument('--output-dir', type=Path, default=None)
    generate.set_defaults(func=_generate)

    build_cmd = sub.add_parser(
        'build', help='assemble the published workshop tree into its branch worktree'
    )
    build_cmd.add_argument('--clean', action='store_true')
    build_cmd.add_argument('--overwrite-dirty', action='store_true')
    build_cmd.set_defaults(func=_build)

    set_cmd = sub.add_parser(
        'set', help='set a [tool.workshopify.params] value and re-render'
    )
    set_cmd.add_argument('key')
    set_cmd.add_argument('value')
    set_cmd.set_defaults(func=_set)

    wt = sub.add_parser('worktree', help='prepare a branch worktree without building')
    wt.add_argument('branch')
    wt.add_argument('--path', type=Path)
    wt.add_argument('--orphan', action='store_true')
    wt.set_defaults(func=_worktree)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except WorkshopifyError as e:
        print(str(e), file=sys.stderr)
        return 1
