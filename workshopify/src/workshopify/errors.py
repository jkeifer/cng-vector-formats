"""The one exception type the whole package reports failures with."""

from __future__ import annotations


class WorkshopifyError(Exception):
    """A diagnosed failure, carrying the message the user should see.

    The message is the whole diagnostic, `error:` prefix included, so the CLI
    boundary can print it unchanged. Deciding to exit is not the same act as
    detecting a problem: everything below `cli.main()` raises this; only the
    CLI turns one into an exit status.
    """
