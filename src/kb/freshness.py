"""Freshness: whether an article or a section is current, from its date and its ttl.

Knowledge articles and their sections are judged by `verified`. Files under
sources/ are copies of outside documents, so they report `synced`, and they
never go stale.
"""

from datetime import date

from kb.meta import ArticleMeta, Invalid, Located
from kb.model import Document, Section

DEFAULT_TTL_DAYS = 60


def status(document: Document, section: Section | None, today: date) -> str:
    """The status shown in headers, such as "stale, verified 2026-08-01 (ttl 60)".

    An unresolved conflict in the article adds ", conflict".
    """
    article = ArticleMeta.read(document, section)
    text = (
        _sources_status(article)
        if document.path.startswith("sources/")
        else (_knowledge_status(article, today))
    )
    if article.conflict == "unresolved":
        text += ", conflict"
    return text


def _sources_status(article: ArticleMeta) -> str:
    if article.synced is None:
        return "unknown"
    if isinstance(article.synced, Invalid):
        return "invalid"
    return f"source, synced {article.synced.isoformat()}"


def _knowledge_status(article: ArticleMeta, today: date) -> str:
    ttl = article.ttl
    # A digit TTL beyond the limit is invalid; an unknown name falls back to the default.
    if isinstance(ttl, Invalid) and ttl.text.isascii() and ttl.text.isdigit():
        return "invalid"
    verified = article.verified
    if verified is None:
        return "unknown"
    if isinstance(verified, Invalid):
        return "invalid"
    days = ttl.value if isinstance(ttl, Located) else DEFAULT_TTL_DAYS
    raw = verified.value.isoformat()
    if (today - verified.value).days > days:
        return f"stale, verified {raw} (ttl {days})"
    return f"fresh, verified {raw}"
