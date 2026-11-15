"""Pure rules that file a transcript observation in the archive instead of the curation queue.

A triaged transcript is saved like any other, but curation never reads it: it is filed in
observations/archived/ with its rule's name in the triage front matter field. A file that
already carries the field is never triaged again, so a file moved back to pending by hand
stays there.
"""

from typing import Literal

from kb.model import Document
from kb.transcripts import Session

Rule = Literal["delegated", "curation"]
FIELD = "triage"
TRANSCRIPT = "session-transcript"
# The skill that kb installs for curation runs.
CURATE_SKILL = "curate"


def for_session(session: Session) -> Rule | None:
    """The rule that a parsed session matches, or None.

    delegated: the session has a parent, so it is a subagent, a guardian review, or another
    delegated thread. curation: the user invoked the curate skill, so the session is a
    curation run. Every part of a matching session matches.
    """
    if session.parent_session:
        return "delegated"
    if CURATE_SKILL in session.invoked:
        return "curation"
    return None


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
