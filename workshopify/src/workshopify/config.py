"""The declarative half of a workshop repo: [tool.workshopify] in pyproject.

Everything mechanical the tool does is driven from here; the one procedural
piece -- the context module -- is only *named* here and executed by
workshopify.context.
"""

from __future__ import annotations

import tomllib

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from workshopify.errors import WorkshopifyError


def _strings(
    table: dict,
    key: str,
    where: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = table.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
        raise WorkshopifyError(f'error: {where} {key} must be a list of strings')
    return tuple(value)


@dataclass(frozen=True)
class RenderConfig:
    files: tuple[str, ...]


@dataclass(frozen=True)
class BuildConfig:
    branch: str = 'workshop'
    include: tuple[str, ...] = ()
    keep_tables: tuple[str, ...] = ('project', 'tool.uv')
    drop_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotebooksConfig:
    src: str = 'src'


@dataclass(frozen=True)
class Config:
    root: Path
    context: Path
    render: RenderConfig
    build: BuildConfig
    notebooks: NotebooksConfig
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def pyproject(self) -> Path:
        return self.root / 'pyproject.toml'

    @classmethod
    def load(cls, root: Path) -> Self:
        root = root.resolve()
        pyproject = root / 'pyproject.toml'
        if not pyproject.is_file():
            raise WorkshopifyError(f'error: no pyproject.toml in {root}')
        with pyproject.open('rb') as f:
            data = tomllib.load(f)
        table = data.get('tool', {}).get('workshopify')
        if table is None:
            raise WorkshopifyError(
                f'error: no [tool.workshopify] table in {pyproject}',
            )
        context = table.get('context')
        if not isinstance(context, str):
            raise WorkshopifyError(
                'error: [tool.workshopify] context must name the context module',
            )
        render = table.get('render', {})
        build = table.get('build', {})
        notebooks = table.get('notebooks', {})
        return cls(
            root=root,
            context=Path(context),
            render=RenderConfig(
                files=_strings(render, 'files', '[tool.workshopify.render]', ()),
            ),
            build=BuildConfig(
                branch=build.get('branch', 'workshop'),
                include=_strings(build, 'include', '[tool.workshopify.build]', ()),
                keep_tables=_strings(
                    build,
                    'keep-tables',
                    '[tool.workshopify.build]',
                    ('project', 'tool.uv'),
                ),
                drop_keys=_strings(
                    build,
                    'drop-keys',
                    '[tool.workshopify.build]',
                    (),
                ),
            ),
            notebooks=NotebooksConfig(src=notebooks.get('src', 'src')),
            params=dict(table.get('params', {})),
        )

    @classmethod
    def discover(cls, start: Path | None = None) -> Self:
        """The nearest enclosing repo with a [tool.workshopify] table."""
        start = (start or Path.cwd()).resolve()
        for candidate in (start, *start.parents):
            pyproject = candidate / 'pyproject.toml'
            if pyproject.is_file():
                with pyproject.open('rb') as f:
                    if 'workshopify' in tomllib.load(f).get('tool', {}):
                        return cls.load(candidate)
        raise WorkshopifyError(
            f'error: no pyproject.toml with [tool.workshopify] at or above {start}',
        )
