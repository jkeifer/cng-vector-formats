import pytest

from workshopify.config import Config
from workshopify.errors import WorkshopifyError

from workshopify import context, render


def _setup(fixture_repo):
    config = Config.load(fixture_repo)
    return config, context.load(config)


def test_fresh_fixture_renders_clean(fixture_repo):
    # The fresh fixture's rendered values are already up to date; the only
    # thing not yet in place is the declared asset, which apply() copies.
    config, ctx = _setup(fixture_repo)
    assert not any('stale rendered values' in e for e in render.check(config, ctx))
    changed = render.apply(config, ctx)
    assert [p.name for p in changed] == ['logo.png']
    assert render.apply(config, ctx) == []


def test_stale_value_is_reported_and_applied(fixture_repo):
    pyproject = fixture_repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('greeting = "hello"', 'greeting = "tena koe"'),
    )
    config, ctx = _setup(fixture_repo)
    errors = render.check(config, ctx)
    stale = [e for e in errors if 'stale rendered values' in e]
    assert len(stale) == 1
    assert 'src/01_example.py' in stale[0]
    changed = render.apply(config, ctx)
    assert '01_example.py' in [p.name for p in changed]
    assert 'word = "tena koe"' in (fixture_repo / 'src/01_example.py').read_text()
    assert '# TENA KOE' in (fixture_repo / 'src/01_example.py').read_text()
    assert render.check(config, ctx) == []


def test_missing_asset_is_reported_and_applied(fixture_repo):
    config, ctx = _setup(fixture_repo)
    target = fixture_repo / 'notebooks/assets/logo.png'
    assert not target.exists()
    # check() reports it while the rendered text is otherwise clean
    # (fresh fixture has no notebooks/assets yet)
    errors = render.check(config, ctx)
    assert any('logo.png' in e for e in errors)
    changed = render.apply(config, ctx)
    assert target.read_bytes() == (fixture_repo / 'assets/logo.png').read_bytes()
    assert target in changed
    assert render.check(config, ctx) == []


def test_stale_asset_is_replaced(fixture_repo):
    config, ctx = _setup(fixture_repo)
    render.apply(config, ctx)
    target = fixture_repo / 'notebooks/assets/logo.png'
    target.write_bytes(b'stale')
    assert any('logo.png' in e for e in render.check(config, ctx))
    render.apply(config, ctx)
    assert target.read_bytes() == (fixture_repo / 'assets/logo.png').read_bytes()


def test_apply_refuses_a_missing_asset_source_before_writing(fixture_repo):
    (fixture_repo / 'assets/logo.png').unlink()
    config, ctx = _setup(fixture_repo)
    with pytest.raises(WorkshopifyError, match='logo.png'):
        render.apply(config, ctx)


def test_publish_strips_markers_and_generators(fixture_repo):
    _config, ctx = _setup(fixture_repo)
    src = (fixture_repo / 'src/01_example.py').read_text()
    stripped = render.publish(src, ctx.namespace, 'src/01_example.py')
    assert '[[[' not in stripped
    assert 'word = "hello"' in stripped
    assert '# HELLO' in stripped


def test_publish_rejects_a_generator_that_breaks_cell_structure(fixture_repo):
    _config, ctx = _setup(fixture_repo)
    # A generator whose output is a bare (uncommented) line inside a markdown
    # cell is not a jupytext fixed point.
    bad = (
        '# %% [markdown]\n'
        '# heading\n'
        '#\n'
        "# <!--[[[cog cog.outl('naked line') ]]]-->\n"
        'naked line\n'
        '# <!--[[[end]]]-->\n'
    )
    with pytest.raises(render.PublishError):
        render.publish(bad, ctx.namespace, '<bad>')


def test_no_files_matched_diagnoses(fixture_repo):
    (fixture_repo / 'src/01_example.py').unlink()
    config, ctx = _setup(fixture_repo)
    with pytest.raises(WorkshopifyError, match='matched nothing'):
        render.check(config, ctx)
