"""The secrets check: detect-secrets' default plugins and filters, run in process over the agent's text.

This is the only module that imports detect_secrets. It does the import inside the scan
function, so the commands that never scan do not pay for it. The text is written to a new
scan file in a directory that the caller names, scanned there, and deleted on every path.
Nothing here makes a network call.
"""

from pathlib import Path

from kb import scratch


def findings(directory: Path, text: str) -> list[tuple[str, int]]:
    """Each possible secret in text, as its detector's name and its line number in text.

    Line numbers count lines split on "\\n", as callers split text. The text is written to a
    new scan file in directory. The file is deleted before this returns, whether or not the
    scan completes.
    """
    from detect_secrets.core.scan import scan_file
    from detect_secrets.settings import default_settings

    path = scratch.create_file(directory, "scan-", ".md", text.encode("utf-8"))
    try:
        with default_settings():
            scanned = [(secret.type, secret.line_number) for secret in scan_file(str(path))]
    finally:
        path.unlink(missing_ok=True)

    text_line_numbers = _text_line_numbers(text)
    return [(detector, text_line_numbers[line_number - 1]) for detector, line_number in scanned]


def _text_line_numbers(text: str) -> list[int]:
    """The "\\n"-split line number of each line that detect-secrets counts in text.

    detect-secrets opens the scan file with universal newlines, so a lone "\\r" also ends a
    line there. Without this map, every finding after a lone "\\r" names a later line.
    """
    text_line_numbers: list[int] = []
    for text_line_number, line in enumerate(text.split("\n"), start=1):
        # A trailing "\r" ends this line with the "\n" after it, or ends the file.
        pieces = line.removesuffix("\r").split("\r")
        text_line_numbers.extend([text_line_number] * len(pieces))
    return text_line_numbers
