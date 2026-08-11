"""The two facts every script in this directory shares.

`scripts/` is not a package -- each file here is a standalone `uv run` target
that also imports its siblings -- so anything more than one of them needs has
to live somewhere both can reach. That is only these two things:

  * `REPO_ROOT`, which was copied into three scripts and drifts the moment one
    of them moves.
  * `ScriptError`, the failure a script diagnosed well enough to report and
    stop on.

`ScriptError` exists so that deciding to exit is not the same act as detecting
a problem. Only a CLI entry point -- a `main()`, or `build_workshop.run()` --
may raise `SystemExit`; everything below it raises `ScriptError` carrying the
message the user should see, and the entry point turns that into the exit. The
alternative, which this replaced, was a data model that terminated the process
on a malformed file: nothing could validate every location and report all the
failures, load two locations to compare them, or test the parser without
asserting on process-exit semantics.

Subclass it where a caller has a reason to tell one failure from another --
`location.LocationError` is the only one today, because a location file is the
one thing here that gets loaded for its own sake.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class ScriptError(Exception):
    """A diagnosed failure, carrying the message the user should see.

    The message is the whole diagnostic, `error:` prefix included, so a CLI
    boundary can hand it to `SystemExit` unchanged.
    """
