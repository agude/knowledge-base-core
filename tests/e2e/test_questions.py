"""End-to-end tests for listing recorded questions."""

from .harness import Kb


def add_question(
    kb: Kb,
    name: str,
    title: str,
    context: str | None,
    body: str,
    created: str | None = "2026-10-26",
) -> None:
    """Add one synthetic question to this test's private content copy."""
    fields = [f'title: "{title}"']
    if context is not None:
        fields.append(f'context: "{context}"')
    if created is not None:
        fields.append(f"created: {created}")
    path = kb.content / "questions" / "open" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + "\n".join(fields) + f"\n---\n\n{body}\n", encoding="utf-8")


def test_lists_open_questions_by_default(kb: Kb) -> None:
    result = kb("questions")
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == (
        "Questions: 1; shown: 1\n"
        "questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open | infra | "
        "Who owns the backup disk?\n"
        "Read with: kb read <locator>\n"
    )


def test_all_includes_resolved_questions_and_old_attribution_forms(kb: Kb) -> None:
    result = kb("questions", "--all")
    assert result.returncode == 0
    assert result.stdout == (
        "Questions: 2; shown: 2\n"
        "questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open | infra | "
        "Who owns the backup disk?\n"
        "questions/resolved/20260915T120000-cccc3333.md | 2026-09-15 | resolved | infra | "
        "Where are the Plex transcoding caches?\n"
        "Read with: kb read <locator>\n"
    )


def test_context_filters_descendants_and_resolves_legacy_shorthand(kb: Kb) -> None:
    add_question(
        kb,
        "child.md",
        "Who owns the archive backup?",
        "knowledge/infra/backups/archive",
        "No owner is recorded.",
    )
    add_question(
        kb,
        "boundary.md",
        "Who owns the infrastructure backup?",
        "knowledge/infrastructure",
        "This context is outside infra.",
    )
    add_question(
        kb,
        "source-context.md",
        "Who owns the vendor guide?",
        "sources/vendor-guide.md",
        "This belongs to sources.",
    )

    result = kb("questions", "--context", "infra")
    assert result.returncode == 0
    assert result.stdout.startswith("Questions: 2; shown: 2\n")
    assert "questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open | infra |" in (
        result.stdout
    )
    assert "questions/open/child.md | 2026-10-26 | open | knowledge/infra/backups/archive |" in (
        result.stdout
    )
    assert "boundary.md" not in result.stdout
    assert "source-context.md" not in result.stdout

    source = kb("questions", "--context", "sources/vendor-guide.md")
    assert source.returncode == 0
    assert source.stdout.startswith("Questions: 1; shown: 1\n")
    assert "questions/open/source-context.md" in source.stdout


def test_deleted_context_stays_visible_and_does_not_follow_a_move(kb: Kb) -> None:
    moved = kb.content / "knowledge" / "projects" / "shapez2" / "new-routing.md"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("# New route\n\nUnrelated.\n", encoding="utf-8")
    deleted = "knowledge/projects/shapez2/routing.md"
    add_question(
        kb,
        "deleted.md",
        "Who owns the route selector?",
        deleted,
        "The selector owner is not recorded.",
    )
    result = kb("questions", "--context", deleted)
    assert result.returncode == 0
    assert result.stdout == (
        "Questions: 1; shown: 1\n"
        f"questions/open/deleted.md | 2026-10-26 | open | {deleted} | "
        "Who owns the route selector?\n"
        "Read with: kb read <locator>\n"
    )
    moved_context = kb("questions", "--context", "knowledge/projects/shapez2/new-routing.md")
    assert moved_context.returncode == 0
    assert moved_context.stdout == "No questions match.\n"


def test_missing_and_invalid_stored_contexts_show_dash_and_are_unfilterable(kb: Kb) -> None:
    add_question(kb, "missing-context.md", "Question without context", None, "No area.")
    add_question(
        kb,
        "invalid-context.md",
        "Question with invalid context",
        "/outside/area",
        "Unsafe area.",
    )
    all_questions = kb("questions")
    assert all_questions.returncode == 0
    assert "questions/open/missing-context.md | 2026-10-26 | open | - |" in all_questions.stdout
    assert "questions/open/invalid-context.md | 2026-10-26 | open | - |" in all_questions.stdout
    filtered = kb("questions", "--context", "knowledge/infra")
    assert filtered.returncode == 0
    assert "missing-context.md" not in filtered.stdout
    assert "invalid-context.md" not in filtered.stdout


def test_date_sorting_limit_total_and_title_clipping(kb: Kb) -> None:
    add_question(kb, "same-z.md", "Z" * 80, "infra", "Z.", "2026-10-10")
    add_question(kb, "same-a.md", "Same date earlier path", "infra", "A.", "2026-10-10")
    add_question(kb, "invalid-date.md", "Invalid date", "infra", "Invalid.", "not-a-date")
    add_question(kb, "missing-date.md", "Missing date", "infra", "Missing.", None)
    add_question(kb, "older.md", "Older", "infra", "Old.", "2025-01-01")

    limited = kb("questions", "--all", "--limit", "2")
    assert limited.returncode == 0
    assert limited.stdout.startswith("Questions: 7; shown: 2\n")
    assert limited.stdout.splitlines()[1].startswith(
        "questions/open/same-a.md | 2026-10-10 | open | infra | Same date earlier path"
    )
    assert limited.stdout.splitlines()[2] == (
        "questions/open/same-z.md | 2026-10-10 | open | infra | " + "Z" * 69 + "..."
    )

    complete = kb("questions", "--all")
    rows = complete.stdout.splitlines()[1:-1]
    assert [row.split(" | ", 1)[0].rsplit("/", 1)[-1] for row in rows] == [
        "same-a.md",
        "same-z.md",
        "20261001T090000-bbbb2222.md",
        "20260915T120000-cccc3333.md",
        "older.md",
        "invalid-date.md",
        "missing-date.md",
    ]
    assert "invalid-date.md |  | open | infra | Invalid date" in complete.stdout
    assert "missing-date.md |  | open | infra | Missing date" in complete.stdout


def test_default_limit_is_twenty_and_total_counts_every_match(kb: Kb) -> None:
    for number in range(21):
        add_question(
            kb,
            f"many-{number:02}.md",
            f"Question {number}",
            "infra",
            "Synthetic question.",
        )
    result = kb("questions")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0] == "Questions: 22; shown: 20"
    assert len(lines) == 22
    assert lines[-1] == "Read with: kb read <locator>"


def test_context_with_no_matches_and_invalid_arguments(kb: Kb) -> None:
    empty = kb("questions", "--context", "knowledge/no-such-area")
    assert empty.returncode == 0
    assert empty.stdout == "No questions match.\n"
    assert empty.stderr == ""

    absolute = kb("questions", "--context", "/outside")
    assert absolute.returncode == 1
    assert absolute.stdout == ""
    assert absolute.stderr == "questions: context must be a relative path\n"

    ambiguous = kb("questions", "--context", "backups.md")
    assert ambiguous.returncode == 1
    assert ambiguous.stderr.startswith('questions: "backups.md" matches 2 files:')

    limit = kb("questions", "--limit", "0")
    assert limit.returncode == 1
    assert limit.stderr == "Option --limit must be a positive integer\n"
    positional = kb("questions", "backup")
    assert positional.returncode == 1
    assert positional.stderr == "Usage: kb questions [--context PATH] [--all] [--limit N]\n"


def test_read_only_listing_preserves_content_bytes_and_git_state(git_kb: Kb) -> None:
    article = git_kb.content / "questions" / "open" / "20261001T090000-bbbb2222.md"
    before_bytes = article.read_bytes()
    before_status = git_kb.git("status", "--porcelain")
    before_head = git_kb.git("rev-parse", "HEAD")
    result = git_kb("questions", "--all", "--context", "infra")
    assert result.returncode == 0
    assert article.read_bytes() == before_bytes
    assert git_kb.git("status", "--porcelain") == before_status
    assert git_kb.git("rev-parse", "HEAD") == before_head


def test_gap_to_list_read_evidence_and_recall(git_kb: Kb) -> None:
    title = "Where is the new backup disk?"
    body = "The new backup disk owner is unknown."
    gap = git_kb("gap", "--title", title, "--body", body, "--context", "infra")
    assert gap.returncode == 0, gap.stderr
    assert git_kb.git("log", "-1", "--format=%s") == f"Ask: {title}\n"
    relative = gap.stdout.removeprefix("Wrote: ").removesuffix("\n")

    listing = git_kb("questions", "--context", "knowledge/infra")
    assert listing.returncode == 0
    assert relative in listing.stdout
    assert f"| open | knowledge/infra | {title}" in listing.stdout

    read = git_kb("read", relative)
    assert read.returncode == 0
    assert body in read.stdout

    found = git_kb("evidence", "new", "backup", "disk", "owner")
    assert found.returncode == 0
    assert f"{relative} | " in found.stdout
    assert "| open question |" in found.stdout

    recalled = git_kb("recall", "backup", "disk")
    assert recalled.returncode == 0
    assert relative in recalled.stdout
    assert "Uncurated (pending, not yet verified):" in recalled.stdout
