"""End-to-end cycle across two clones of one bare origin: observe, sync, curate, finish, recall."""

import re

from .harness import Kb, run_git

WROTE = re.compile(r"Wrote: observations/pending/([0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.md)\n")
RUN = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
ARTICLE = (
    "---\ntitle: Cycle\nupdated: 2026-10-26\nverified: 2026-10-26\nttl: domain\n---\n"
    "# Cycle\n\n## 1. Durable fact\n\nThe cycle keeps one durable fact.\n"
)


def test_two_clones_share_one_origin_across_observe_start_finish_and_recall(
    remote_git_kb: Kb,
) -> None:
    clone_a = remote_git_kb
    assert clone_a.origin is not None
    clone_b_path = clone_a.home / "clone-b"
    run_git(clone_a.home, "clone", "-q", str(clone_a.origin), str(clone_b_path))
    clone_b = Kb(home=clone_a.home, content=clone_b_path, origin=clone_a.origin)

    observed = clone_a("observe", "--title", "Cycle note", "--body", "The cycle keeps one fact.")
    assert observed.returncode == 0, observed.stderr
    name_match = WROTE.search(observed.stdout)
    assert name_match is not None, observed.stdout
    name = name_match.group(1)
    synced = clone_a("sync")
    assert synced.returncode == 0, synced.stderr
    assert "Pushed: 1 commit(s)" in synced.stdout

    started = clone_b("curate", "start", "--max-bytes", "100000", name)
    assert started.returncode == 0, started.stderr
    assert "Pulled: 1 commit(s)" in started.stdout
    run_match = RUN.search(started.stdout)
    assert run_match is not None, started.stdout
    run = run_match.group(1)
    (clone_b.content / "knowledge" / "cycle.md").write_text(ARTICLE, encoding="utf-8")
    completed = clone_b(
        "curate", "complete", run, name, "--disposition", "incorporated", "knowledge/cycle.md"
    )
    assert completed.returncode == 0, completed.stderr

    finished = clone_b("curate", "finish", run)

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert "Published: origin/main\n" in finished.stdout

    pulled = clone_a("sync")
    assert pulled.returncode == 0, pulled.stderr
    assert "Pulled: 1 commit(s)" in pulled.stdout
    recalled = clone_a("recall", "durable fact")
    assert recalled.returncode == 0, recalled.stderr
    assert "knowledge/cycle.md" in recalled.stdout
    assert "The cycle keeps one durable fact." in recalled.stdout
    assert not (clone_a.content / "observations" / "pending" / name).exists()
    assert (clone_a.content / "observations" / "archived" / name).is_file()
