import pytest

from conftest import git_repo
from workshopify.errors import WorkshopifyError
from workshopify.git import git, succeeds


def test_git_returns_stdout(tmp_path):
    repo = git_repo(tmp_path / 'r')
    assert git(repo, 'rev-parse', '--abbrev-ref', 'HEAD').strip() == 'main'


def test_git_failure_carries_the_diagnostic(tmp_path):
    repo = git_repo(tmp_path / 'r')
    with pytest.raises(WorkshopifyError) as excinfo:
        git(repo, 'rev-parse', '--verify', 'no-such-ref')
    assert 'rev-parse' in str(excinfo.value)


def test_succeeds_probes_quietly(tmp_path):
    repo = git_repo(tmp_path / 'r')
    assert succeeds(repo, 'rev-parse', '--git-dir')
    assert not succeeds(repo, 'show-ref', '--verify', '--quiet', 'refs/heads/nope')
