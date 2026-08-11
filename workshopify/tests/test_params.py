import pytest

from workshopify.errors import WorkshopifyError
from workshopify.params import set_param


def test_set_rewrites_the_param_and_rerenders(fixture_repo):
    changed = set_param(fixture_repo, 'greeting', 'kia ora')
    text = (fixture_repo / 'pyproject.toml').read_text()
    assert 'greeting = "kia ora"' in text
    src = (fixture_repo / 'src/01_example.py').read_text()
    assert 'word = "kia ora"' in src
    assert '# KIA ORA' in src
    assert any(p.name == '01_example.py' for p in changed)


def test_set_preserves_pyproject_comments(fixture_repo):
    pyproject = fixture_repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace(
            '[tool.workshopify.params]',
            '# which greeting ships\n[tool.workshopify.params]',
        ),
    )
    set_param(fixture_repo, 'greeting', 'howdy')
    assert '# which greeting ships' in pyproject.read_text()


def test_set_rejects_an_unknown_param(fixture_repo):
    with pytest.raises(WorkshopifyError, match="no param 'nope'"):
        set_param(fixture_repo, 'nope', 'x')
    assert 'nope' not in (fixture_repo / 'pyproject.toml').read_text()


def test_set_rolls_back_when_rendering_fails(fixture_repo):
    """A failure must modify nothing: the param rewrite lands first because
    rendering reads it back, so a failing render undoes the rewrite."""
    original = (fixture_repo / 'pyproject.toml').read_text()
    src_before = (fixture_repo / 'src/01_example.py').read_text()
    (fixture_repo / 'context.py').write_text(
        "if params['greeting'] == 'boom':\n"
        "    raise RuntimeError('kaboom')\n"
        "word = params['greeting']\n"
        'def shout():\n'
        '    return word.upper()\n',
    )
    with pytest.raises(WorkshopifyError):
        set_param(fixture_repo, 'greeting', 'boom')
    assert (fixture_repo / 'pyproject.toml').read_text() == original
    assert (fixture_repo / 'src/01_example.py').read_text() == src_before


def test_set_to_the_current_value_still_restores_assets(fixture_repo):
    target = fixture_repo / 'notebooks/assets/logo.png'
    assert not target.exists()
    set_param(fixture_repo, 'greeting', 'hello')
    assert target.is_file()
