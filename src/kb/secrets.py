"""The secrets check: detect-secrets' default plugins and filters, run in process over the agent's text.

This is the only module that imports detect_secrets. It does the import inside the scan
function, so the commands that never scan do not pay for it. The text is written to a new
scan file in a directory that the caller names, scanned there, and deleted on every path.
Nothing here makes a network call.
"""

import os
from pathlib import Path


def findings(directory: Path, text: str) -> list[tuple[str, int]]:
    """Each possible secret in text, as its detector's name and its line number in text.

    The text is written to a new scan file in directory. The file is deleted before this
    returns, whether or not the scan completes.
    """
    from detect_secrets.core.scan import scan_file
    from detect_secrets.settings import default_settings

    path = directory / f"scan-{os.urandom(4).hex()}.md"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        with default_settings():
            return [(secret.type, secret.line_number) for secret in scan_file(str(path))]
    finally:
        path.unlink(missing_ok=True)
