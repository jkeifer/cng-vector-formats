"""Put scripts/ on sys.path so the tests can import the scripts as modules.

This project is not a package (`[tool.uv] package = false`), so there is no
installed distribution to import from.
"""

import subprocess
import sys

from pathlib import Path

# The one copy for the tests, imported by the other modules as
# `from conftest import REPO`. It used to be recomputed in each of them, which
# is four chances to disagree about where the repository is. The scripts' own
# copy lives in scripts/common.py.
REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / 'scripts'))

# Below the sys.path insert above, which is what makes set_location importable.
import pytest
import set_location

# Every file a retarget writes. Guarded below.
TRACKED = [
    Path('pyproject.toml'),
    *(Path('src') / name for name in set_location.SRC_FILES),
    set_location.ACTIVE_SCREENSHOT,
]

# The publish target. build_workshop's build/clean write here for real, and
# --clean deletes every tracked file, so a test that reached main() rather
# than run() would rebuild -- or empty -- the developer's own worktree.
WORKSHOP = REPO / 'workshop'


def _workshop_state() -> str | None:
    """A fingerprint of the workshop worktree, or None if there isn't one.

    HEAD plus porcelain status rather than file hashes: it catches a commit,
    a modification, a deletion and a new untracked file, without walking the
    gigabytes of ignored byte cache that live under there.
    """
    if not (WORKSHOP / '.git').exists():
        return None
    result = subprocess.run(
        ['git', '-C', str(WORKSHOP), 'status', '--porcelain', '-b'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    head = subprocess.run(
        ['git', '-C', str(WORKSHOP), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        check=False,
    )
    return f'{head.stdout}\n{result.stdout}'


@pytest.fixture(autouse=True, scope='session')
def _real_repo_is_untouched():
    """Fail if anything in the suite writes to the real repository.

    `main()` and `retarget()` default to `set_location.REPO_ROOT`, so a test
    that calls one without redirecting that constant retargets the developer's
    checkout (and CI's) for real. That happened once on this branch, silently.

    Session-scoped and in conftest deliberately: the guard used to live in
    test_set_location.py at module scope, which left every other module --
    including test_location.py, which reads the real src/ -- unwatched.

    The workshop worktree is watched for the same reason: it is a real
    directory a test can destroy, and until this covered it, nothing would
    have noticed.
    """
    before = {path: (REPO / path).read_bytes() for path in TRACKED}
    workshop_before = _workshop_state()
    yield
    changed = [
        str(path) for path, data in before.items() if (REPO / path).read_bytes() != data
    ]
    assert not changed, f'the test suite modified the real repository: {changed}'
    assert _workshop_state() == workshop_before, (
        'the test suite modified the real workshop worktree'
    )
