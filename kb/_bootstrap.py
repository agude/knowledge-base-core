"""Start an executable's command module, or fail the way its role requires.

The `sh` preamble has already chosen an interpreter, but that choice can be
stale: `.python-interpreter` qualifies by existing, not by version. This
module therefore re-checks the version before importing anything else from
`kb`, and must stay importable by old interpreters: no syntax newer than
Python 3.9 (ruff checks it as py39) and no imports beyond `os`,
`subprocess`, and `sys`.
"""

import os
import subprocess
import sys

MINIMUM = (3, 11)


def fail(script, message):
    """Exit as the preamble's kb_fail does for the executable at script."""
    path = script.replace(os.sep, "/")
    if path.endswith("/session-context"):
        sys.stdout.write(message + "\n")
        sys.exit(0)
    name = path.rsplit("/", 1)[-1]
    if "/adapters/" in path or name.startswith("session-"):
        sys.exit(0)
    if path.endswith("/hooks/pre-commit"):
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", "knowledge/"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
        if not staged:
            sys.exit(0)
    sys.stderr.write(message + "\n")
    sys.exit(1)


def run(module, script):
    """Import module and call its main(); return its exit status."""
    if sys.version_info < MINIMUM:
        fail(
            script,
            f"knowledge base: needs Python 3.11 or newer; {sys.executable} is {sys.version_info[0]}.{sys.version_info[1]}",
        )
    import importlib

    from kb import platform
    from kb.content import UsageError

    platform.exit_on_signals()
    try:
        return importlib.import_module(module).main(sys.argv[1:])
    except UsageError as error:
        sys.stderr.write(f"{error}\n")
        return 1
