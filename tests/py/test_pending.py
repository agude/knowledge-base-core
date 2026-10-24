"""pending: list, count, and preview uncurated observations."""

from __future__ import annotations

import shutil

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result

# Epochs used by the bats suite for --preview ages.
EPOCH_2026_09_05 = "1788566400"
EPOCH_2026_09_06 = "1788652800"


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


def _pending_dir(kb: KB):
    return kb.layout.content / "observations" / "pending"


@pytest.mark.bats("pending.bats", "pending reports no observations when the directory is missing")
@pytest.mark.bats("pending.bats", "pending --count reports 0 when the directory is missing")
@pytest.mark.parametrize("args", [[], ["--count"], ["--full"], ["--preview"]])
def test_pending_missing_directory(kb: KB, golden: Golden, args: list[str]) -> None:
    shutil.rmtree(_pending_dir(kb))
    _check(kb, golden, kb.run("pending", *args))


@pytest.mark.bats("pending.bats", "pending shows 0 when empty")
@pytest.mark.parametrize("args", [[], ["--count"], ["--full"]])
def test_pending_empty(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("pending", *args))


@pytest.mark.bats("pending.bats", "pending --count returns correct number")
@pytest.mark.bats("pending.bats", "pending lists titles")
@pytest.mark.bats("pending.bats", "pending --full shows file content")
@pytest.mark.parametrize("args", [[], ["--count"], ["--full"]])
def test_pending_listing(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_observation("b.md", "Second", "Body two")
    kb.create_observation("a.md", "First observation", "Full body text here")
    _check(kb, golden, kb.run("pending", *args))


@pytest.mark.bats(
    "pending.bats", "pending --preview reports age, type counts, volume, and topic hints"
)
def test_preview_metrics(kb: KB, golden: Golden) -> None:
    kb.create_article("networking.md", "# Networking Setup")
    kb.create_observation("a.md", "Networking failure", "The Networking Setup needs attention.")
    (_pending_dir(kb) / "transcript.md").write_text(
        '---\ntitle: "Session transcript"\nsource: session-transcript\n'
        "created: 2026-05-01T00:00:00Z\n---\n\nTranscript body.\n",
        encoding="utf-8",
    )
    result = kb.run("pending", "--preview", env={"FRESHNESS_TODAY_EPOCH": EPOCH_2026_09_05})
    _check(kb, golden, result)


@pytest.mark.bats("pending.bats", "pending --preview is bounded for malformed and large inputs")
def test_preview_malformed_and_large(kb: KB, golden: Golden) -> None:
    (_pending_dir(kb) / "broken.md").write_text(
        "title: Broken metadata\ncreated: not-a-date\n", encoding="utf-8"
    )
    (_pending_dir(kb) / "large.md").write_text(
        '---\ntitle: "Large transcript"\nsource: session-transcript\n'
        "created: 2026-05-01T00:00:00Z\n---\n" + "x" * 20000 + "\n",
        encoding="utf-8",
    )
    result = kb.run("pending", "--preview", env={"FRESHNESS_TODAY_EPOCH": EPOCH_2026_09_05})
    _check(kb, golden, result)
    assert "xxxxxxxxxx" not in result.out
    assert len(result.out) < 2000


@pytest.mark.bats("pending.bats", "pending keeps recursive listing and bounds preview selection")
@pytest.mark.audit("A-022")
def test_nested_observations(kb: KB, golden: Golden) -> None:
    kb.create_observation("top-level.md", "Top-level observation", "Body")
    nested = _pending_dir(kb) / "nested"
    nested.mkdir()
    (nested / "hidden.md").write_text(
        '---\ntitle: "Nested observation"\nsource: session\n'
        "created: 2025-01-01T00:00:00Z\n---\n\nBody\n",
        encoding="utf-8",
    )
    golden.check("count", kb.run("pending", "--count").out)
    golden.check("list", kb.norm(kb.run("pending").out))
    golden.check("full", kb.norm(kb.run("pending", "--full").out))
    result = kb.run("pending", "--preview", env={"FRESHNESS_TODAY_EPOCH": EPOCH_2026_09_06})
    _check(kb, golden, result)


@pytest.mark.bats("pending.bats", "pending --preview decodes escaped topic labels")
def test_preview_escaped_topic(kb: KB, golden: Golden) -> None:
    (_pending_dir(kb) / "escaped.md").write_text(
        '---\ntitle: "Escaped topic"\nsource: session\ncreated: 2026-04-12T00:00:00Z\n'
        'topic: "Team \\"Core\\""\n---\n\nBody\n',
        encoding="utf-8",
    )
    _check(kb, golden, kb.run("pending", "--preview"))


@pytest.mark.bats("pending.bats", "pending --preview caps metadata and topic corpus work")
def test_preview_caps_topic_corpus(kb: KB, golden: Golden) -> None:
    for index in range(1, 321):
        kb.create_article(f"topics/topic-{index}.md", f"# Topic {index}")
    (_pending_dir(kb) / "large.md").write_text(
        '---\ntitle: "Large transcript"\nsource: session-transcript\n'
        "created: 2026-05-01T00:00:00Z\n---\nTopic\n" + "x" * 262144 + "\n",
        encoding="utf-8",
    )
    result = kb.run("pending", "--preview", env={"FRESHNESS_TODAY_EPOCH": EPOCH_2026_09_05})
    _check(kb, golden, result)
    assert len(result.out) < 2000


@pytest.mark.bats("pending.bats", "pending --preview reports an empty queue without warnings")
def test_preview_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("pending", "--preview"))


@pytest.mark.bats("pending.bats", "pending --preview selects input within a byte budget")
def test_preview_byte_budget(kb: KB, golden: Golden) -> None:
    small = kb.create_observation("a.md", "A", "small")
    kb.create_observation("b.md", "B", "a larger observation body that exceeds the budget")
    cap = str(small.stat().st_size)
    _check(kb, golden, kb.run("pending", "--preview", "--max-bytes", cap))


@pytest.mark.bats(
    "pending.bats", "pending --preview accepts a zero-byte budget without selecting files"
)
def test_preview_zero_budget(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body")
    _check(kb, golden, kb.run("pending", "--preview", "--max-bytes", "0"))


@pytest.mark.bats("pending.bats", "pending preview rejects an invalid byte budget")
@pytest.mark.parametrize("value", ["nope", "-1", ""])
def test_preview_invalid_budget(kb: KB, golden: Golden, value: str) -> None:
    _check(kb, golden, kb.run("pending", "--preview", "--max-bytes", value))


@pytest.mark.bats("pending.bats", "pending preview bounds oversized-item reporting")
def test_preview_bounds_oversized_report(kb: KB, golden: Golden) -> None:
    for index in range(1, 26):
        kb.create_observation(f"oversized-{index}.md", f"Observation {index}", f"Body {index}")
    result = kb.run("pending", "--preview", "--max-bytes", "0")
    _check(kb, golden, result)
    assert len(result.out) < 2500


@pytest.mark.bats("pending.bats", "preview ignores metadata years and isolated common topic words")
def test_preview_topic_matching(kb: KB, golden: Golden) -> None:
    kb.create_article("bike.md", "# Canyon Neuron 6 (2026)")
    kb.create_article("handoff.md", "# Handing a Claude Code Session Between Machines")
    kb.create_article("pdf.md", "# PDF Skill")
    for name, title, body in [
        ("a.md", "Unrelated skill", "A session captured a tooling change."),
        ("b.md", "Canyon Neuron ride", "The descent felt stable."),
        ("c.md", "PDF extraction", "Extract the document text."),
    ]:
        path = kb.create_observation(name, title, body)
        path.write_text(path.read_text(encoding="utf-8").replace("2026-04-12", "2026-09-06"))
    _check(kb, golden, kb.run("pending", "--preview"))


@pytest.mark.bats(
    "pending.bats", "preview and batch select identical ordered input within a byte budget"
)
def test_preview_matches_batch_selection(kb: KB, golden: Golden) -> None:
    a = kb.create_observation("a.md", "First", "A")
    b = kb.create_observation("b.md", "Second", "B")
    kb.create_observation("c.md", "Oversized", "large" * 100)
    cap = str(a.stat().st_size + b.stat().st_size)
    preview = kb.run("pending", "--preview", "--max-bytes", cap)
    _check(kb, golden, preview)
    batch = kb.run("batch", "start", "--max-bytes", cap)
    assert batch.returncode == 0
    manifests = sorted((kb.layout.content / "observations" / "batches").glob("*.tsv"))
    assert len(manifests) == 1
    rows = manifests[0].read_text(encoding="utf-8").splitlines()[1:]
    assert [row.split("\t")[0] for row in rows] == ["a.md", "b.md"]


def test_pending_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("pending", "--bogus"))
