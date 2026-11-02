"""Tests for the token cache: freshness, storage, recovery, and where the cache lives."""

import dataclasses
import os
import pickle
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from kb import addressing, chunks, corpus, entries, evidence, lock, model, search, token_cache
from kb.entries import Entry, PartTokens

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRANSCRIPT = (
    "---\n"
    "title: Session transcript: restart\n"
    "source: session-transcript\n"
    "session: restart-session\n"
    "part: 1\n"
    "first_message: restart-1\n"
    "last_message: restart-2\n"
    "started: 2026-10-01T09:00:00Z\n"
    "ended: 2026-10-01T09:05:00Z\n"
    "created: 2026-10-01T09:10:00Z\n"
    "---\n"
    "\n"
    "## 1. user, 2026-10-01T09:00:00Z\n"
    "\n"
    "Restart the NAS before Traefik.\n"
    "\n"
    "## 2. assistant, 2026-10-01T09:05:00Z\n"
    "\n"
    "The NAS restarted first.\n"
)
INJECTED = (
    "---\n"
    "title: Session transcript: kitchen\n"
    "source: session-transcript\n"
    "session: kitchen-session\n"
    "part: 1\n"
    "first_message: kitchen-1\n"
    "last_message: kitchen-3\n"
    "started: 2026-10-02T10:00:00Z\n"
    "ended: 2026-10-02T10:20:00Z\n"
    "created: 2026-10-02T10:20:00Z\n"
    "---\n"
    "\n"
    "## 1. user, 2026-10-02T10:00:00Z\n"
    "\n"
    "~~~~text\n"
    "Inventory the kitchen.\n"
    "~~~~\n"
    "\n"
    "## 2. user, 2026-10-02T10:05:00Z\n"
    "\n"
    "~~~~text\n"
    "<INSTRUCTIONS>Rotate the zigzag cipher key.</INSTRUCTIONS>\n"
    "~~~~\n"
    "\n"
    "## 3. user, 2026-10-02T10:10:00Z\n"
    "\n"
    "~~~~text\n"
    "# AGENTS.md instructions for /repo\n"
    "\n"
    "Rotate the zigzag cipher key too.\n"
    "~~~~\n"
)


def observation(title: str, body: str) -> str:
    return f"---\ntitle: {title}\ncreated: 2026-10-01\n---\n\n# {title}\n\n{body}\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    return root


def write(root: Path, relpath: str, text: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = make_repo(tmp_path / "content")
    write(root, "observations/pending/20261001T090000-nas.md", observation("NAS", "Restart it."))
    write(root, "observations/archived/20261001T100000-traefik.md", TRANSCRIPT)
    write(root, "questions/open/nas.md", observation("Open NAS", "Why first?"))
    return root


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every text that search.index_tokens is asked to tokenize, in order."""
    calls: list[str] = []
    original = search.index_tokens

    def counting(text: str) -> tuple[str, ...]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(search, "index_tokens", counting)
    return calls


def reference_unit(document: model.Document) -> search.Unit:
    """The unit an evidence file had before the cache: its title and its body prose."""
    body = document.prose(document.body_start, len(document.lines))
    return search.make_unit(document.title or "", (), (), body)


def paths(root: Path) -> list[str]:
    return token_cache.evidence_paths(root)


def stored(root: Path) -> dict[str, Entry]:
    target = token_cache.cache_file(root)
    assert target is not None
    loaded = token_cache._decode(target, token_cache.fingerprint())
    assert loaded is not None
    return loaded


@pytest.fixture
def decodes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every cache file that token_cache decodes from disk, in order."""
    calls: list[Path] = []
    original = token_cache._decode

    def counting(target: Path, version: str) -> dict[str, Entry] | None:
        calls.append(target)
        return original(target, version)

    monkeypatch.setattr(token_cache, "_decode", counting)
    monkeypatch.setattr(token_cache, "_memo", None)
    return calls


def test_loads_in_one_process_decode_an_unchanged_cache_file_once(
    repo: Path, decodes: list[Path]
) -> None:
    token_cache.load(repo, paths(repo))
    decodes.clear()
    first = token_cache.load(repo, paths(repo)[:1])
    second = token_cache.load(repo, paths(repo))
    assert decodes == []
    assert set(first) <= set(second)


def test_a_cache_file_changed_on_disk_is_decoded_again(repo: Path, decodes: list[Path]) -> None:
    token_cache.load(repo, paths(repo))
    target = token_cache.cache_file(repo)
    assert target is not None
    token_cache._memo = None
    token_cache.load(repo, paths(repo))
    assert decodes == [target, target]

    decodes.clear()
    data = target.read_bytes()
    target.write_bytes(data + b"\0")
    token_cache.load(repo, paths(repo))
    assert decodes == [target]


def test_a_cold_build_and_a_warm_load_agree_and_the_warm_load_tokenizes_nothing(
    repo: Path, counted: list[str]
) -> None:
    cold = token_cache.load(repo, paths(repo))
    target = token_cache.cache_file(repo)
    assert target is not None and target.exists()
    assert counted

    counted.clear()
    warm = token_cache.load(repo, paths(repo))
    assert counted == []
    assert warm == cold
    assert sorted(cold) == paths(repo)


def test_entries_hold_the_tokens_that_the_documents_give_for_every_fixture_file(
    repo: Path,
) -> None:
    fixture_files = sorted(FIXTURES.rglob("*.md"))
    assert fixture_files
    names = []
    for file in fixture_files:
        relpath = "observations/archived/" + "-".join(file.relative_to(FIXTURES).parts)
        write(repo, relpath, file.read_text(encoding="utf-8"))
        names.append(relpath)

    loaded = token_cache.load(repo, names)
    assert sorted(loaded) == sorted(names)
    parts_seen = 0
    for relpath in names:
        document = corpus.read_document(repo, relpath)
        entry = loaded[relpath]
        assert entry.title == search.index_tokens(document.title or "")
        assert entry.addressable is (addressing.message_sections(document) is not None)
        if evidence.evidence_kind(relpath, document.scalar("source")) == "transcript":
            found = chunks.parts(document)
            assert [(p.number, p.timestamp, p.piece, p.size) for p in entry.parts] == [
                (p.number, p.timestamp, p.piece, p.size) for p in found
            ]
            for part, cached in zip(found, entry.parts, strict=True):
                assert cached.body == tuple(
                    token for line in part.lines for token in search.index_tokens(line)
                )
            assert entry.body == ()
            parts_seen += len(entry.parts)
        else:
            assert entry.parts == ()
            assert entries.file_unit(entry) == reference_unit(document)
        assert set(entry.scalars) <= set(token_cache.SCALAR_FIELDS)
        for name in token_cache.SCALAR_FIELDS:
            assert entry.scalars.get(name) == document.scalar(name)
    assert parts_seen > 0


def test_a_touched_file_updates_its_stat_and_is_not_tokenized_again(
    repo: Path, counted: list[str]
) -> None:
    token_cache.load(repo, paths(repo))
    target = repo / "observations/pending/20261001T090000-nas.md"
    before = target.stat()
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))

    counted.clear()
    report = token_cache.refresh(repo)
    assert counted == []
    assert report == token_cache.RefreshReport(refreshed=0, restated=1, removed=0, written=True)
    entry = stored(repo)["observations/pending/20261001T090000-nas.md"]
    assert entry.mtime_ns == before.st_mtime_ns + 5_000_000_000


def test_an_edited_file_is_tokenized_again_and_no_other_file_is(repo: Path) -> None:
    token_cache.load(repo, paths(repo))
    before = stored(repo)
    write(
        repo, "observations/pending/20261001T090000-nas.md", observation("NAS", "Restart Traefik.")
    )

    report = token_cache.refresh(repo)
    assert report == token_cache.RefreshReport(refreshed=1, restated=0, removed=0, written=True)
    after = stored(repo)
    changed = "observations/pending/20261001T090000-nas.md"
    assert after[changed].body != before[changed].body
    assert "traefik" in entries.file_unit(after[changed]).body
    for relpath in after:
        if relpath != changed:
            assert after[relpath] == before[relpath]


def test_a_deleted_file_drops_its_entry(repo: Path) -> None:
    token_cache.load(repo, paths(repo))
    (repo / "questions/open/nas.md").unlink()

    report = token_cache.refresh(repo)
    assert report == token_cache.RefreshReport(refreshed=0, restated=0, removed=1, written=True)
    assert "questions/open/nas.md" not in stored(repo)


def test_a_load_keeps_the_entries_of_paths_it_was_not_asked_for(repo: Path) -> None:
    token_cache.load(repo, ["observations/pending/20261001T090000-nas.md"])
    token_cache.load(repo, ["questions/open/nas.md"])
    assert set(stored(repo)) == {
        "observations/pending/20261001T090000-nas.md",
        "questions/open/nas.md",
    }


def test_a_missing_path_is_left_out_of_the_result(repo: Path) -> None:
    entries = token_cache.load(repo, ["observations/pending/missing.md", "questions/open/nas.md"])
    assert list(entries) == ["questions/open/nas.md"]


def test_a_file_that_cannot_be_read_is_left_out_of_the_result(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_bytes

    def unreadable(self: Path) -> bytes:
        if self.name == "nas.md":
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    entries = token_cache.load(repo, paths(repo))
    assert "questions/open/nas.md" not in entries
    assert "observations/pending/20261001T090000-nas.md" in entries


def test_a_new_fingerprint_rebuilds_everything(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_cache.load(repo, paths(repo))
    monkeypatch.setattr(token_cache, "fingerprint", lambda package=None: "other")
    report = token_cache.refresh(repo)
    assert report.refreshed == len(paths(repo))


def test_a_new_format_rebuilds_everything(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_cache.load(repo, paths(repo))
    monkeypatch.setattr(token_cache, "FORMAT", token_cache.FORMAT + 1)
    report = token_cache.refresh(repo)
    assert report.refreshed == len(paths(repo))


def _package_copy(tmp_path: Path) -> Path:
    package = tmp_path / "kb"
    shutil.copytree(
        Path(token_cache.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    return package


def test_the_fingerprint_matches_a_copy_of_the_package(tmp_path: Path) -> None:
    package = _package_copy(tmp_path)
    assert token_cache.fingerprint(package) == token_cache.fingerprint()


@pytest.mark.parametrize("name", ["addressing.py", "corpus.py", "hosts/claude.py", "cli.py"])
def test_an_edit_to_any_package_source_changes_the_fingerprint(tmp_path: Path, name: str) -> None:
    package = _package_copy(tmp_path)
    baseline = token_cache.fingerprint(package)
    source = package / name
    original = source.read_bytes()
    source.write_bytes(original + b"\n# edit\n")
    assert token_cache.fingerprint(package) != baseline
    source.write_bytes(original)
    assert token_cache.fingerprint(package) == baseline


def test_every_python_file_under_the_package_is_fingerprinted(tmp_path: Path) -> None:
    package = _package_copy(tmp_path)
    baseline = token_cache.fingerprint(package)
    sources = sorted(package.rglob("*.py"))
    assert any(path.parent != package for path in sources)
    for source in sources:
        original = source.read_bytes()
        source.write_bytes(original + b"\n# edit\n")
        assert token_cache.fingerprint(package) != baseline, source
        source.write_bytes(original)


def test_renaming_a_package_source_changes_the_fingerprint(tmp_path: Path) -> None:
    package = _package_copy(tmp_path)
    baseline = token_cache.fingerprint(package)
    (package / "addressing.py").rename(package / "addressing_renamed.py")
    assert token_cache.fingerprint(package) != baseline


CORRUPT_KINDS = (
    "truncated",
    "wrong-top-type",
    "missing-key",
    "entries-not-a-dict",
    "wrong-entry",
    "key-mismatch",
    "not-a-pickle",
)


def corrupt_payloads(version: str) -> dict[str, Callable[[Path], None]]:
    def write_bytes(target: Path, data: Any) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def pickled(target: Path, payload: object) -> None:
        write_bytes(target, pickle.dumps(payload, protocol=5))

    def truncated(target: Path) -> None:
        pickled(target, {"format": token_cache.FORMAT, "fingerprint": version, "entries": {}})
        data = target.read_bytes()
        target.write_bytes(data[: len(data) // 2])

    def wrong_top_type(target: Path) -> None:
        pickled(target, [1, 2])

    def missing_key(target: Path) -> None:
        pickled(target, {"format": token_cache.FORMAT, "fingerprint": version})

    def entries_not_a_dict(target: Path) -> None:
        pickled(
            target,
            {"format": token_cache.FORMAT, "fingerprint": version, "entries": []},
        )

    def wrong_entry(target: Path) -> None:
        pickled(
            target,
            {"format": token_cache.FORMAT, "fingerprint": version, "entries": {"x": ("bad",)}},
        )

    def key_mismatch(target: Path) -> None:
        pickled(
            target,
            {
                "format": token_cache.FORMAT,
                "fingerprint": version,
                "entries": {"other.md": _valid_entry("nas.md")},
            },
        )

    def not_bytes_a_pickle(target: Path) -> None:
        write_bytes(target, b"not a pickle")

    return {
        "truncated": truncated,
        "wrong-top-type": wrong_top_type,
        "missing-key": missing_key,
        "entries-not-a-dict": entries_not_a_dict,
        "wrong-entry": wrong_entry,
        "key-mismatch": key_mismatch,
        "not-a-pickle": not_bytes_a_pickle,
    }


def _valid_entry(path: str) -> Entry:
    return token_cache._build(model.parse(path, "# NAS\n\nRestart it.\n"), 1, 2, "digest")


@pytest.mark.parametrize("kind", CORRUPT_KINDS)
def test_an_unreadable_cache_is_rebuilt_from_the_files(repo: Path, kind: str) -> None:
    token_cache.load(repo, paths(repo))
    target = token_cache.cache_file(repo)
    assert target is not None
    corrupt_payloads(token_cache.fingerprint())[kind](target)

    report = token_cache.refresh(repo)
    assert report.refreshed == len(paths(repo))
    assert sorted(stored(repo)) == paths(repo)


def test_a_pickle_of_an_earlier_format_rebuilds_everything(repo: Path) -> None:
    token_cache.load(repo, paths(repo))
    target = token_cache.cache_file(repo)
    assert target is not None
    earlier = {
        "format": token_cache.FORMAT - 1,
        "fingerprint": token_cache.fingerprint(),
        "entries": stored(repo),
    }
    target.write_bytes(pickle.dumps(earlier, protocol=5))
    report = token_cache.refresh(repo)
    assert report.refreshed == len(paths(repo))
    assert sorted(stored(repo)) == paths(repo)


def test_the_cache_holds_only_records_and_builtin_types(repo: Path) -> None:
    token_cache.load(repo, paths(repo))

    def assert_plain(value: object) -> None:
        if isinstance(value, Entry):
            for field in dataclasses.fields(value):
                assert_plain(getattr(value, field.name))
        elif isinstance(value, PartTokens):
            for item in value:
                assert_plain(item)
        elif isinstance(value, datetime):
            return
        elif isinstance(value, dict):
            for key, item in value.items():
                assert_plain(key)
                assert_plain(item)
        elif isinstance(value, tuple):
            for item in value:
                assert_plain(item)
        else:
            assert type(value) in (str, int, bool, type(None)), type(value)

    target = token_cache.cache_file(repo)
    assert target is not None
    with target.open("rb") as handle:
        assert_plain(pickle.load(handle))


def test_a_cache_that_cannot_be_created_warns_once_and_returns_correct_entries(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = token_cache.cache_file(repo)
    assert target is not None
    # A file where the cache directory belongs makes every write fail, on any platform.
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    target.parent.write_text("not a directory", encoding="utf-8")

    entries = token_cache.load(repo, paths(repo))
    assert sorted(entries) == paths(repo)
    err = capsys.readouterr().err
    assert err.count("token cache not written") == 1
    assert err.count("\n") == 1


def test_a_failed_replace_warns_and_leaves_no_temporary_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "replace", refuse)
    entries = token_cache.load(repo, paths(repo))
    assert sorted(entries) == paths(repo)
    assert "token cache not written" in capsys.readouterr().err
    target = token_cache.cache_file(repo)
    assert target is not None
    assert list(target.parent.glob(".tokens-*.tmp")) == []


def test_a_held_lock_means_correct_entries_and_no_write(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = token_cache.cache_file(repo)
    assert target is not None
    target.parent.mkdir(parents=True, exist_ok=True)
    backend = lock.default_backend(sys.platform)
    descriptor = lock.acquire_kernel(target.parent / token_cache.LOCK_FILE, backend, 0)
    try:
        report = token_cache.refresh(repo)
        assert report == token_cache.RefreshReport(
            refreshed=3, restated=0, removed=0, written=False
        )
        assert not target.exists()
        assert capsys.readouterr().err == ""
        entries = token_cache.load(repo, paths(repo))
        assert sorted(entries) == paths(repo)
    finally:
        backend.unlock(descriptor)
        os.close(descriptor)


def test_the_cache_lands_in_the_git_directory_of_each_worktree(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "content")
    git(
        root,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-qm",
        "Start",
    )
    worktree = tmp_path / "worktree"
    git(root, "worktree", "add", "-q", str(worktree))

    main = token_cache.cache_file(root)
    other = token_cache.cache_file(worktree)
    assert main == (root / ".git" / "kb" / "tokens.pickle").resolve()
    assert other is not None
    assert other.is_relative_to((root / ".git" / "worktrees").resolve())


def test_outside_a_git_repository_nothing_is_cached_or_written(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    write(plain, "observations/pending/20261001T090000-nas.md", observation("NAS", "Restart it."))
    assert token_cache.cache_file(plain) is None

    entries = token_cache.load(plain, token_cache.evidence_paths(plain))
    assert list(entries) == ["observations/pending/20261001T090000-nas.md"]
    assert not (plain / ".git").exists()
    report = token_cache.refresh(plain)
    assert report.written is False


def test_a_missing_content_root_has_no_cache(tmp_path: Path) -> None:
    assert token_cache.cache_file(tmp_path / "absent") is None


def test_a_content_root_inside_another_repository_gets_no_cache(tmp_path: Path) -> None:
    outer = make_repo(tmp_path / "outer")
    inner = outer / "content"
    write(inner, "observations/pending/20261001T090000-nas.md", observation("NAS", "Restart it."))
    assert token_cache.cache_file(inner) is None
    assert token_cache.cache_file(outer) == (outer / ".git" / "kb" / "tokens.pickle").resolve()
    report = token_cache.refresh(inner)
    assert report.written is False
    assert not (outer / ".git" / "kb").exists()


def test_status_reports_missing_stale_and_current(repo: Path) -> None:
    target = token_cache.cache_file(repo)
    assert target is not None
    assert token_cache.status(repo).state == "missing"

    token_cache.load(repo, paths(repo))
    current = token_cache.status(repo)
    assert current == token_cache.CacheStatus(target, 3, target.stat().st_size, "current")

    write(repo, "questions/open/nas.md", "Changed length.\n")
    assert token_cache.status(repo).state == "stale"
    token_cache.refresh(repo)
    assert token_cache.status(repo).state == "current"

    (repo / "questions/open/nas.md").unlink()
    assert token_cache.status(repo).state == "stale"


def test_status_is_stale_when_the_cache_file_is_unusable(repo: Path) -> None:
    token_cache.load(repo, paths(repo))
    target = token_cache.cache_file(repo)
    assert target is not None
    target.write_bytes(b"not a pickle")
    assert token_cache.status(repo) == token_cache.CacheStatus(target, 0, 12, "stale")


def test_status_outside_a_worktree_is_none(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    write(plain, "observations/pending/20261001T090000-nas.md", observation("NAS", "Restart it."))
    assert token_cache.status(plain) == token_cache.CacheStatus(None, 0, 0, "none")


def test_an_empty_repository_still_gets_a_current_cache(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "content")
    assert token_cache.refresh(root).written is True
    assert token_cache.status(root).state == "current"


def test_an_entry_whose_file_is_gone_is_not_on_disk(tmp_path: Path) -> None:
    entry = token_cache._build(model.parse("gone.md", "# Gone\n"), 1, 2, "digest")
    assert token_cache._on_disk(tmp_path, entry) is False


def test_injected_text_is_not_tokenized_into_a_transcript_entry(repo: Path) -> None:
    relpath = "observations/archived/20261002T100000-kitchen.md"
    write(repo, relpath, INJECTED)
    entry = token_cache.load(repo, [relpath])[relpath]

    secret = set(search.index_tokens("zigzag cipher"))
    assert secret
    assert not secret & set(entry.body)
    assert not any(secret & set(part.body) for part in entry.parts)
    assert not any(secret & set(chunk.body) for chunk in entries.chunk_tokens(entry))
    kitchen = set(search.index_tokens("kitchen"))
    assert kitchen <= {token for part in entry.parts for token in part.body}
    # Message 3 is an AGENTS.md instruction message, which chunking drops, so it has no part.
    assert sorted(entries.message_bodies(entry)) == [1, 2]


def test_chunk_tokens_match_the_search_units_of_the_chunks(repo: Path) -> None:
    relpath = "observations/archived/20261001T100000-traefik.md"
    document = corpus.read_document(repo, relpath)
    entry = token_cache.load(repo, [relpath])[relpath]
    expected = [
        (
            chunk.number,
            chunk.last,
            chunk.started,
            chunk.ended,
            chunk.piece,
            search.make_unit("", (), (), list(chunk.lines)).body,
        )
        for chunk in chunks.chunks(document)
    ]
    actual = [
        (found.number, found.last, found.started, found.ended, found.piece, found.body)
        for found in entries.chunk_tokens(entry)
    ]
    assert actual == expected
    assert actual


def test_only_transcripts_carry_parts(repo: Path) -> None:
    loaded = token_cache.load(repo, paths(repo))
    assert loaded["observations/pending/20261001T090000-nas.md"].parts == ()
    assert loaded["questions/open/nas.md"].parts == ()
    assert loaded["observations/archived/20261001T100000-traefik.md"].parts
