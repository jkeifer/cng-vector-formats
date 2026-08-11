from pathlib import Path

import pytest

from workshopify.config import Config
from workshopify.errors import WorkshopifyError


def test_load_reads_the_tables(fixture_repo):
    config = Config.load(fixture_repo)
    assert config.root == fixture_repo.resolve()
    assert config.context == Path('context.py')
    assert config.render.files == ('src/*.py',)
    assert config.build.include == ('Dockerfile',)
    assert config.params == {'greeting': 'hello'}


def test_defaults(fixture_repo):
    config = Config.load(fixture_repo)
    assert config.build.branch == 'workshop'
    assert config.build.keep_tables == ('project', 'tool.uv')
    assert config.build.drop_keys == ()
    assert config.notebooks.src == 'src'
    assert config.pyproject == fixture_repo.resolve() / 'pyproject.toml'


def test_load_without_table_diagnoses(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
    with pytest.raises(WorkshopifyError, match=r'no \[tool\.workshopify\] table'):
        Config.load(tmp_path)


def test_load_without_pyproject_diagnoses(tmp_path):
    with pytest.raises(WorkshopifyError, match='no pyproject.toml'):
        Config.load(tmp_path)


def test_discover_walks_up_from_a_subdirectory(fixture_repo):
    sub = fixture_repo / 'src'
    assert Config.discover(sub).root == fixture_repo.resolve()


def test_discover_ignores_a_pyproject_without_the_table(fixture_repo, tmp_path):
    with pytest.raises(WorkshopifyError, match='workshopify'):
        Config.discover(tmp_path)


def test_render_files_must_be_strings(fixture_repo):
    pyproject = fixture_repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('files = ["src/*.py"]', 'files = [1]'),
    )
    with pytest.raises(WorkshopifyError, match='files'):
        Config.load(fixture_repo)
