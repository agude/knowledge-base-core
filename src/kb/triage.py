"""Pure rules that file a transcript observation in the archive instead of the curation queue.

A triaged transcript is saved like any other, but curation never reads it: it is filed in
observations/archived/ with its rule's name in the triage front matter field. A file that
already carries the field is never triaged again, so a file moved back to pending by hand
stays there.
"""

from typing import Literal

from kb.model import Document

Rule = Literal["delegated", "curation"]
FIELD = "triage"
TRANSCRIPT = "session-transcript"


def from_front_matter(document: Document) -> Rule | None:
    """The rule that a committed observation's front matter matches, or None.

    Only delegated is visible in front matter: a transcript whose session has a parent is a
    subagent, a guardian review, or another delegated thread.
    """
    if FIELD in document.front or document.scalar("source") != TRANSCRIPT:
        return None
    if document.scalar("parent_session"):
        return "delegated"
    return None
