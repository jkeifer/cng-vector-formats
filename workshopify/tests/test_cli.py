import json
import subprocess

from workshopify.cli import main


def test_render_applies_and_reports(fixture_repo, monkeypatch, capsys):
    monkeypatch.chdir(fixture_repo)
    assert main(['render']) == 0
    assert 'logo.png' in capsys.readouterr().err  # the asset was placed


def test_check_clean_after_render(fixture_repo, monkeypatch):
    monkeypatch.chdir(fixture_repo)
    main(['render'])
    assert main(['check']) == 0


def test_check_reports_staleness_nonzero(fixture_repo, monkeypatch, capsys):
    monkeypatch.chdir(fixture_repo)
    main(['render'])
    pyproject = fixture_repo / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('greeting = "hello"', 'greeting = "yo"'),
    )
    assert main(['check']) == 1
    assert 'stale' in capsys.readouterr().err


def test_set_and_check_roundtrip(fixture_repo, monkeypatch):
    monkeypatch.chdir(fixture_repo)
    assert main(['set', 'greeting', 'kia ora']) == 0
    assert main(['check']) == 0


def test_generate_into_a_directory(fixture_repo, monkeypatch, tmp_path):
    monkeypatch.chdir(fixture_repo)
    out = tmp_path / 'out'
    assert main(['generate', '--output-dir', str(out)]) == 0
    nb = out / 'notebooks' / '01_example.ipynb'
    assert json.loads(nb.read_text())['cells']


def test_a_diagnosed_failure_prints_and_exits_one(fixture_repo, monkeypatch, capsys):
    monkeypatch.chdir(fixture_repo)
    assert main(['set', 'nope', 'x']) == 1
    assert 'error:' in capsys.readouterr().err


def test_worktree_subcommand(fixture_repo, monkeypatch, capsys):
    from conftest import git_repo

    git_repo(fixture_repo)
    subprocess.run(['git', 'add', '-A'], cwd=fixture_repo, check=True)
    subprocess.run(['git', 'commit', '-qm', 'x'], cwd=fixture_repo, check=True)
    monkeypatch.chdir(fixture_repo)
    assert main(['worktree', 'pub']) == 0
    assert (fixture_repo / 'pub' / '.git').exists()


def test_build_publishes_into_the_branch_worktree(fixture_repo, monkeypatch):
    from conftest import git_repo

    git_repo(fixture_repo)
    subprocess.run(['git', 'add', '-A'], cwd=fixture_repo, check=True)
    subprocess.run(['git', 'commit', '-qm', 'x'], cwd=fixture_repo, check=True)
    subprocess.run(['uv', 'lock'], cwd=fixture_repo, check=True)
    monkeypatch.chdir(fixture_repo)
    assert main(['build']) == 0
    assert (fixture_repo / 'workshop' / 'Dockerfile').is_file()
    assert (fixture_repo / 'workshop' / 'notebooks' / '01_example.ipynb').is_file()
