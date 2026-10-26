"""Failures that end a command with one message on stderr and exit status 1."""


class KbError(Exception):
    """A failure to report to the user. Its message is printed as it is."""
