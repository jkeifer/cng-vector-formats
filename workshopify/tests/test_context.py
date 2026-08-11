import pytest

from workshopify.config import Config
from workshopify.errors import WorkshopifyError

from workshopify import context


def test_namespace_carries_module_level_names(fixture_repo):
    ctx = context.load(Config.load(fixture_repo))
    assert ctx.namespace['word'] == 'hello'
    assert ctx.namespace['shout']() == 'HELLO'


def test_params_are_injected(fixture_repo):
    pyproject = fixture_repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('greeting = "hello"', 'greeting = "kia ora"'),
    )
    ctx = context.load(Config.load(fixture_repo))
    assert ctx.namespace['word'] == 'kia ora'


def test_assets_resolve_against_the_root(fixture_repo):
    ctx = context.load(Config.load(fixture_repo))
    assert ctx.assets == {
        (fixture_repo / 'notebooks/assets/logo.png').resolve(): (
            fixture_repo / 'assets/logo.png'
        ).resolve(),
    }


def test_sibling_imports_work(fixture_repo):
    (fixture_repo / 'helper.py').write_text('VALUE = 42\n')
    (fixture_repo / 'context.py').write_text(
        'from helper import VALUE\nword = str(VALUE)\n',
    )
    ctx = context.load(Config.load(fixture_repo))
    assert ctx.namespace['word'] == '42'


def test_missing_context_module_diagnoses(fixture_repo):
    (fixture_repo / 'context.py').unlink()
    with pytest.raises(WorkshopifyError, match='context module'):
        context.load(Config.load(fixture_repo))


def test_a_workshopify_error_in_the_module_passes_through(fixture_repo):
    (fixture_repo / 'context.py').write_text(
        'from workshopify.errors import WorkshopifyError\n'
        "raise WorkshopifyError('error: no such location')\n",
    )
    with pytest.raises(WorkshopifyError, match='no such location'):
        context.load(Config.load(fixture_repo))


def test_an_arbitrary_crash_is_wrapped_with_the_module_named(fixture_repo):
    (fixture_repo / 'context.py').write_text('boom\n')
    with pytest.raises(WorkshopifyError, match='context.py'):
        context.load(Config.load(fixture_repo))


def test_assets_must_be_a_dict(fixture_repo):
    (fixture_repo / 'context.py').write_text("word = 'x'\nASSETS = ['nope']\n")
    with pytest.raises(WorkshopifyError, match='ASSETS'):
        context.load(Config.load(fixture_repo))
