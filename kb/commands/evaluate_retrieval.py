"""evaluate-retrieval - Measure lexical retrieval against a versioned fixture.

Usage:
  evaluate-retrieval --fixture FILE [--content-dir DIR]
                     [--baseline FILE] [--write-baseline FILE]
                     [--max-bytes N]
                     [--fail-on-regression]

Options:
  --fixture FILE          Versioned JSON question fixture (required)
  --content-dir DIR       Content repository to evaluate
  --baseline FILE         Compare ranked results with a frozen baseline
  --write-baseline FILE   Write ranked results as a new frozen baseline
  --fail-on-regression    Exit nonzero when a baseline outcome regresses
  --max-bytes N           Bound each search response by stdout bytes
  --json                  Accepted for consistency; JSON is always returned

The evaluator measures full-ranking and bounded search subprocesses. It
reports distinct-locator top-five coverage, first relevant rank, response
bytes, wall-clock latency, and false-positive retrieval for unanswerable
cases. It does not call a model or modify the content repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kb import cli, frontmatter, paths, platform
from kb.commands import section as section_command
from kb.content import content_dir, nonnegative

ROLES = ("unspecified", "pre_change", "post_implementation", "comparison")
COMMANDS = ("--alias", "--top", "--title")
SEARCH_CORPUS = ("knowledge/", "sources/", "observations/pending/")


def _num(value: float) -> float | int:
    """jq prints an integral number without a fraction."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _dump(value: object, indent: int | None = None) -> str:
    separators = None if indent else (",", ":")
    return json.dumps(value, ensure_ascii=False, indent=indent, separators=separators).replace(
        "\x7f", "\\u007f"
    )


def _is(value: object, kind: type) -> bool:
    return isinstance(value, kind) and not (kind is int and isinstance(value, bool))


def valid_fixture(data: Any) -> bool:
    """The version 1 question fixture schema."""
    if not isinstance(data, dict):
        return False
    role = data.get("evaluation_role") or "unspecified"
    cases = data.get("cases")
    if not (
        data.get("format") == "knowledge-base-retrieval-evaluation"
        and data.get("version") == 1
        and _is(data.get("fixture_id"), str)
        and data["fixture_id"]
        and _is(data.get("corpus_id"), str)
        and data["corpus_id"]
        and role in ROLES
        and isinstance(cases, list)
        and cases
    ):
        return False
    ids = [case.get("id") if isinstance(case, dict) else None for case in cases]
    if len(ids) != len({json.dumps(i) for i in ids}):
        return False
    for case in cases:
        if not isinstance(case, dict):
            return False
        expected = case.get("expected_sections")
        group = case.get("comparison_group")
        if not (
            _is(case.get("id"), str)
            and case["id"]
            and _is(case.get("category"), str)
            and _is(case.get("query"), str)
            and case["query"]
            and (case.get("query_mode") or "literal") in ("literal", "question")
            and isinstance(case.get("relax") or False, bool)
            and (group is None or (_is(group, str) and group))
            and isinstance(expected, list)
            and isinstance(case.get("requires_all_sections"), bool)
            and isinstance(case.get("unanswerable"), bool)
        ):
            return False
        for item in expected:
            if not isinstance(item, dict):
                return False
            number, command = item.get("number"), item.get("command")
            if not (
                _is(item.get("path"), str)
                and item["path"]
                and _is(item.get("section"), str)
                and item["section"]
                and (number is None or (_is(number, str) and number))
                and (command is None or (_is(command, str) and command in COMMANDS))
                and (number is None or command is None)
            ):
                return False
        if case["unanswerable"] == bool(expected):
            return False
    return True


def validate_locators(content: Path, fixture: dict[str, Any]) -> None:
    """Every expected locator exists in the corpus, as section finds it."""
    for case in fixture["cases"]:
        if case["unanswerable"]:
            continue
        case_id = case["id"]
        for expected in case["expected_sections"]:
            path, heading = expected["path"], expected["section"]
            number, command = expected.get("number") or "", expected.get("command") or ""
            try:
                resolved = paths.resolve(content, path)
            except paths.PathError:
                resolved = None
            if resolved is None:
                cli.fail(
                    f"Invalid retrieval fixture: case '{case_id}' expected locator path not found: {path}"
                )
            if resolved != path:
                cli.fail(
                    f"Invalid retrieval fixture: case '{case_id}' locator path must be content-relative: {path}"
                )
            if not (resolved.startswith(SEARCH_CORPUS) and resolved.endswith(".md")):
                cli.fail(
                    f"Invalid retrieval fixture: case '{case_id}' expected locator is outside the selected search corpus: {path}"
                )
            file = Path(f"{content}/{resolved}")
            if not file.is_file():
                cli.fail(
                    f"Invalid retrieval fixture: case '{case_id}' expected locator path not found: {path}"
                )
            if (heading == "top" and not number and not command) or command == "--alias":
                continue
            text = platform.read_text(file)
            error = ""
            if command == "--title":
                title = frontmatter.field(text, "title")
                found = (title, "", "--title") if title else None
                error = "Title not found"
            elif command == "--top":
                found = ("top", "", "--top")
            else:
                match = section_command.find_section(
                    text, number, "" if number else heading, not number
                )
                found = (match.heading, match.number, "") if match.found else None
                if not match.found:
                    error = (
                        f"Section #{number} not found (file has {match.h2_count} H2 sections)"
                        if number
                        else f"Heading not found: '{heading}'"
                    )
            if found is None:
                print(
                    f"Invalid retrieval fixture: case '{case_id}' expected locator section not found: {path} | {heading}\n  {error}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            actual, actual_number, actual_command = found
            if (
                (number and actual_number != number)
                or (command and actual_command != command)
                or (not number and not command and actual != heading)
            ):
                cli.fail(
                    f"Invalid retrieval fixture: case '{case_id}' locator section does not match corpus heading: "
                    f"{path} | {heading} (actual: {actual})"
                )


def corpus_sha(content: Path) -> str:
    """A hash of every Markdown file's relative path and content hash, in byte order."""
    files = []
    for directory, _, names in os.walk(content):
        for name in names:
            path = Path(directory) / name
            if name.endswith(".md") and path.is_file() and not path.is_symlink():
                files.append(path)
    manifest = "".join(
        f"{str(path).removeprefix(f'{content}/')}\t{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in sorted(files, key=bytes)
    )
    return hashlib.sha256(manifest.encode("utf-8", errors="surrogateescape")).hexdigest()


def _locator(result: dict[str, Any]) -> dict[str, Any]:
    locator = result.get("locator") or {}
    return {
        "path": result.get("path"),
        "section": locator.get("section") or "top",
        "number": locator.get("number"),
        "command": locator.get("command"),
        "routing": result.get("routing") is True,
    }


def _distinct(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for result in results:
        locator = _locator(result)
        key = (
            locator["path"],
            locator["section"],
            locator["number"] or "",
            locator["command"] or "",
        )
        if key not in seen:
            seen.add(key)
            out.append(locator)
    return out


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if actual["path"] != expected["path"]:
        return False
    if expected.get("number") is not None:
        return actual["number"] == expected["number"]
    if expected.get("command") is not None:
        return actual["command"] == expected["command"]
    return actual["section"] == expected["section"]


def case_record(
    case: dict[str, Any],
    full: dict[str, Any],
    bounded: dict[str, Any],
    sizes: tuple[int, int],
    latencies: tuple[int, int],
) -> dict[str, Any]:
    """One case's measurements (evaluate-retrieval-case.jq)."""
    all_results = full.get("results") or []
    bounded_results = bounded.get("results") or []
    expected = case.get("expected_sections") or []
    full_evidence = _distinct([r for r in all_results if r.get("routing") is not True])
    full_ranking = _distinct(all_results)
    bounded_evidence = _distinct([r for r in bounded_results if r.get("routing") is not True])
    routing_results = [_locator(r) for r in bounded_results if r.get("routing") is True]
    expected_evidence = [e for e in expected if (e.get("command") or "") != "--alias"]
    expected_routing = [e for e in expected if e.get("command") == "--alias"]
    unanswerable = case.get("unanswerable") is True
    requires_all = case.get("requires_all_sections") is True
    retrieved = bool(full_evidence)
    false_positive = unanswerable and retrieved
    routing_success = any(_matches(r, e) for r in routing_results for e in expected_routing)
    top_five: list[dict[str, Any]] = []
    for locator in _distinct(bounded_results):
        compact = {"path": locator["path"], "section": locator["section"]}
        if compact not in top_five:
            top_five.append(compact)
    matched = sum(1 for e in expected_evidence if any(_matches(r, e) for r in bounded_evidence))
    ranks = [
        i + 1 for i, r in enumerate(full_ranking) if any(_matches(r, e) for e in expected_evidence)
    ]
    first_rank = ranks[0] if ranks else None
    if unanswerable:
        any_, all_, evidence = None, None, None
    elif not expected_evidence:
        any_ = all_ = False
        evidence = all_ if requires_all else any_
    else:
        any_, all_ = matched > 0, matched == len(expected_evidence)
        evidence = all_ if requires_all else any_
    if unanswerable:
        success = None
    elif expected_routing and expected_evidence:
        success = routing_success and evidence
    elif expected_routing:
        success = routing_success
    else:
        success = evidence
    if unanswerable and retrieved:
        status = "false_positive"
    elif unanswerable:
        status = "unanswerable"
    else:
        status = "pass" if success else "fail"
    if false_positive:
        failure = "retrieval returned evidence for an unanswerable query"
    elif unanswerable or success:
        failure = None
    elif expected_routing and not routing_success:
        failure = "expected alias routing result was not recovered"
    elif requires_all:
        failure = "not all expected sections appear in the top five"
    else:
        failure = "no expected section appears in the top five"
    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "query_mode": case.get("query_mode") or "literal",
        "relaxed_query": case.get("relax") or False,
        "comparison_group": case.get("comparison_group"),
        "retained_terms": full.get("query_terms") or [],
        "matching_mode": full.get("match_mode") or "strict",
        "output_budget_bytes": full.get("max_bytes"),
        "full_omitted_results": full.get("omitted_results") or 0,
        "top_five_omitted_results": bounded.get("omitted_results") or 0,
        "expected_sections": expected,
        "requires_all_sections": requires_all,
        "unanswerable": unanswerable,
        "status": status,
        "any_required_evidence": any_,
        "all_required_evidence": all_,
        "routing_success": None if unanswerable else routing_success,
        "false_positive_retrieval": retrieved if unanswerable else None,
        "matched_required_evidence_count": None if unanswerable else matched,
        "first_relevant_rank": first_rank,
        "full_ranking_result_count": len(all_results),
        "full_ranking_response_bytes": sizes[0],
        "full_ranking_latency_ms": latencies[0],
        "top_five_raw_result_count": len(bounded_results),
        "top_five_section_count": len(top_five),
        "top_five_response_bytes": sizes[1],
        "top_five_latency_ms": latencies[1],
        "bounded_raw_results": [
            {
                "path": r.get("path"),
                "section": (r.get("locator") or {}).get("section") or "top",
                "number": (r.get("locator") or {}).get("number"),
                "command": (r.get("locator") or {}).get("command"),
                "line": (r.get("locator") or {}).get("line"),
                "text": r.get("text"),
            }
            for r in bounded_results
        ],
        "top_five": top_five,
        "failure": failure,
    }


def _grouped(items: list[dict[str, Any]], key: str) -> list[list[dict[str, Any]]]:
    """jq group_by: groups sorted by key, stable within a group."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(item.get(key), []).append(item)
    return [groups[k] for k in sorted(groups, key=lambda k: (k is not None, k or ""))]


def _rate(part: int, whole: int) -> float | int | None:
    return None if whole == 0 else _num(part / whole)


def report(
    fixture: dict[str, Any], cases: list[dict[str, Any]], shas: tuple[str, str], role: str
) -> dict[str, Any]:
    answerable = [c for c in cases if c["unanswerable"] is False]
    failures = [c for c in cases if c["status"] == "fail" or c["false_positive_retrieval"] is True]

    def count(items: list[dict[str, Any]], key: str) -> int:
        return sum(1 for c in items if c.get(key) is True)

    categories = [
        {
            "category": group[0]["category"],
            "total_cases": len(group),
            "answerable_cases": sum(1 for c in group if c["unanswerable"] is False),
            "passed_cases": sum(1 for c in group if c["status"] == "pass"),
            "any_required_evidence_cases": count(group, "any_required_evidence"),
            "all_required_evidence_cases": count(group, "all_required_evidence"),
            "routing_success_cases": count(group, "routing_success"),
            "false_positive_unanswerable_cases": count(group, "false_positive_retrieval"),
        }
        for group in _grouped(cases, "category")
    ]
    comparison_groups = []
    for group in _grouped(
        [c for c in cases if c["comparison_group"] is not None], "comparison_group"
    ):
        strict = [c for c in group if c["relaxed_query"] is False]
        relaxed = [c for c in group if c["relaxed_query"] is True]
        comparison_groups.append(
            {
                "comparison_group": group[0]["comparison_group"],
                "strict_case_count": len(strict),
                "relaxed_case_count": len(relaxed),
                "strict_passed_cases": sum(1 for c in strict if c["status"] == "pass"),
                "relaxed_passed_cases": sum(1 for c in relaxed if c["status"] == "pass"),
                "discovery_gain": any(c["status"] == "fail" for c in strict)
                and any(c["status"] == "pass" for c in relaxed),
                "added_false_positive": any(
                    c["false_positive_retrieval"] is not True for c in strict
                )
                and any(c["false_positive_retrieval"] is True for c in relaxed),
            }
        )
    unanswerable = len(cases) - len(answerable)
    budget = cases[0]["output_budget_bytes"] if cases else None
    return {
        "format": "knowledge-base-retrieval-evaluation-report",
        "version": 1,
        "fixture_id": fixture["fixture_id"],
        "corpus_id": fixture["corpus_id"],
        "evaluation_role": role,
        "fixture_sha256": shas[0],
        "corpus_sha256": shas[1],
        "measurement": {
            "top_k": 5,
            "coverage_unit": "distinct search locators (path, section, number/command) from the bounded top-five response",
            "full_ranking_command": "search --json --limit 0 --per-file 0 QUERY",
            "top_five_command": "search --json --limit 5 --per-file 0 QUERY",
            "full_ranking_latency_scope": "wall-clock time for the full-ranking search subprocess",
            "top_five_latency_scope": "wall-clock time for the bounded top-five search subprocess",
            "latency_clock": "milliseconds from Python's monotonic clock (time.perf_counter_ns)",
            "response_bytes": "UTF-8 bytes in each search JSON stdout response, including its trailing newline",
            "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "summary": {
            "total_cases": len(cases),
            "answerable_cases": len(answerable),
            "unanswerable_cases": unanswerable,
            "passed_cases": sum(1 for c in answerable if c["status"] == "pass"),
            "failed_cases": len(failures),
            "any_required_evidence_cases": count(cases, "any_required_evidence"),
            "all_required_evidence_cases": count(cases, "all_required_evidence"),
            "routing_success_cases": count(cases, "routing_success"),
            "false_positive_unanswerable_cases": count(cases, "false_positive_retrieval"),
            "any_required_evidence_rate": _rate(
                count(cases, "any_required_evidence"), len(answerable)
            ),
            "all_required_evidence_rate": _rate(
                count(cases, "all_required_evidence"), len(answerable)
            ),
            "routing_success_rate": _rate(count(cases, "routing_success"), len(answerable)),
            "false_positive_unanswerable_rate": _rate(
                count(cases, "false_positive_retrieval"), unanswerable
            ),
            "categories": categories,
            "query_modes": [
                {"mode": g[0]["query_mode"], "cases": len(g)} for g in _grouped(cases, "query_mode")
            ],
            "comparison_groups": comparison_groups,
            "relaxation": {
                "compared_groups": len(comparison_groups),
                "discovery_gain_groups": sum(1 for g in comparison_groups if g["discovery_gain"]),
                "added_false_positive_groups": sum(
                    1 for g in comparison_groups if g["added_false_positive"]
                ),
            },
            "output_budget_bytes": budget,
            "full_omitted_results_total": sum(c["full_omitted_results"] for c in cases),
            "top_five_omitted_results_total": sum(c["top_five_omitted_results"] for c in cases),
            "full_ranking_response_bytes_total": sum(
                c["full_ranking_response_bytes"] for c in cases
            ),
            "top_five_response_bytes_total": sum(c["top_five_response_bytes"] for c in cases),
            "full_ranking_latency_ms_total": sum(c["full_ranking_latency_ms"] for c in cases),
            "top_five_latency_ms_total": sum(c["top_five_latency_ms"] for c in cases),
        },
        "failures": [
            {
                k: c[k]
                for k in (
                    "id",
                    "category",
                    "query",
                    "expected_sections",
                    "status",
                    "failure",
                    "false_positive_retrieval",
                    "first_relevant_rank",
                    "top_five",
                )
            }
            for c in failures
        ],
        "cases": cases,
    }


BASELINE_FIELDS = (
    "id",
    "query_mode",
    "relaxed_query",
    "comparison_group",
    "status",
    "any_required_evidence",
    "all_required_evidence",
    "routing_success",
    "false_positive_retrieval",
    "matched_required_evidence_count",
    "first_relevant_rank",
    "full_ranking_result_count",
    "full_ranking_response_bytes",
    "top_five_raw_result_count",
    "top_five_section_count",
    "top_five_response_bytes",
    "top_five",
)
COMPARED = (
    "status",
    "first_relevant_rank",
    "any_required_evidence",
    "all_required_evidence",
    "false_positive_retrieval",
    "matched_required_evidence_count",
    "full_ranking_result_count",
    "full_ranking_response_bytes",
    "top_five_raw_result_count",
    "top_five_section_count",
    "top_five_response_bytes",
    "top_five",
)
CURRENT_FIELDS = (
    "status",
    "any_required_evidence",
    "all_required_evidence",
    "routing_success",
    "false_positive_retrieval",
    "matched_required_evidence_count",
    "first_relevant_rank",
    "full_ranking_result_count",
    "full_ranking_response_bytes",
    "top_five_raw_result_count",
    "top_five_section_count",
    "top_five_response_bytes",
    "top_five",
)


def baseline(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "knowledge-base-retrieval-evaluation-baseline",
        "version": 1,
        **{
            k: current[k]
            for k in (
                "fixture_id",
                "corpus_id",
                "evaluation_role",
                "fixture_sha256",
                "corpus_sha256",
            )
        },
        "top_k": 5,
        "cases": [{k: case.get(k) for k in BASELINE_FIELDS} for case in current["cases"]],
    }


def compare(current: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    by_id = {case["id"]: case for case in frozen["cases"]}
    current_ids = [case["id"] for case in current["cases"]]
    frozen_ids = [case["id"] for case in frozen["cases"]]
    changed = []
    for case in current["cases"]:
        old = by_id.get(case["id"])
        if old is None:
            continue
        differs = (
            any(case.get(k) != old.get(k) for k in COMPARED)
            or (case.get("query_mode") or "literal") != (old.get("query_mode") or "literal")
            or (case.get("relaxed_query") or False) != (old.get("relaxed_query") or False)
            or (case.get("routing_success") or False) != (old.get("routing_success") or False)
        )
        if differs:
            changed.append(
                {
                    "id": case["id"],
                    "baseline": old,
                    "current": {k: case.get(k) for k in CURRENT_FIELDS},
                }
            )
    details = []
    for item in changed:
        old, new = item["baseline"], item["current"]
        reasons = []
        if old.get("status") == "pass" and new["status"] != "pass":
            reasons.append("status")
        if old.get("first_relevant_rank") is not None and (
            new["first_relevant_rank"] is None
            or new["first_relevant_rank"] > old["first_relevant_rank"]
        ):
            reasons.append("first_relevant_rank")
        if old.get("any_required_evidence") is True and new["any_required_evidence"] is not True:
            reasons.append("any_required_evidence")
        if old.get("all_required_evidence") is True and new["all_required_evidence"] is not True:
            reasons.append("all_required_evidence")
        if (old.get("routing_success") or False) is True and new["routing_success"] is not True:
            reasons.append("routing_success")
        if (
            old.get("false_positive_retrieval") is not True
            and new["false_positive_retrieval"] is True
        ):
            reasons.append("false_positive_retrieval")
        if (new["matched_required_evidence_count"] or 0) < (
            old.get("matched_required_evidence_count") or 0
        ):
            reasons.append("matched_required_evidence_count")
        if reasons:
            details.append({"id": item["id"], "reasons": reasons})
    return {
        "fixture_match": current["fixture_sha256"] == frozen.get("fixture_sha256"),
        "evaluation_role_match": (current.get("evaluation_role") or "unspecified")
        == (frozen.get("evaluation_role") or "unspecified"),
        "baseline_fixture_sha256": frozen.get("fixture_sha256"),
        "current_fixture_sha256": current["fixture_sha256"],
        "corpus_match": current["corpus_sha256"] == frozen.get("corpus_sha256"),
        "baseline_corpus_sha256": frozen.get("corpus_sha256"),
        "current_corpus_sha256": current["corpus_sha256"],
        "changed_cases": changed,
        "regressions": [d["id"] for d in details],
        "regression_details": details,
        "improvements": [
            c["id"]
            for c in changed
            if c["baseline"].get("status") == "fail" and c["current"]["status"] == "pass"
        ],
        "missing_baseline_cases": [i for i in current_ids if i not in frozen_ids],
        "extra_baseline_cases": [i for i in frozen_ids if i not in current_ids],
        "unchanged_case_count": sum(1 for i in current_ids if i in by_id) - len(changed),
    }


def _search(
    executable: Path, content: Path, case: dict[str, Any], limit: int, max_bytes: int | None
) -> tuple[bytes, bytes, int, int]:
    """One search subprocess: stdout, stderr, exit status, and wall-clock milliseconds.

    A subprocess on purpose: latency is defined as the time of the search
    process (see the plan's constraints).
    """
    args = [str(executable), "--json", "--limit", str(limit), "--per-file", "0"]
    if max_bytes is not None:
        args += ["--max-bytes", str(max_bytes)]
    if (case.get("query_mode") or "literal") == "question":
        args += ["--query", case["query"]]
        if case.get("relax") or False:
            args.append("--relax")
    else:
        args += ["--", case["query"]]
    started = time.perf_counter_ns()
    result = subprocess.run(
        args, env={**os.environ, "KB_CONTENT_DIR": str(content)}, capture_output=True, check=False
    )
    elapsed = (time.perf_counter_ns() - started) // 1_000_000
    return result.stdout, result.stderr, result.returncode, elapsed


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={
            "--fixture": "fixture",
            "--content-dir": "content-dir",
            "--baseline": "baseline",
            "--write-baseline": "write-baseline",
            "--max-bytes": "max-bytes",
        },
        flags={"--fail-on-regression": "fail", "--json": "json"},
    )
    max_bytes = (
        nonnegative("--max-bytes", args.get("max-bytes")) if "max-bytes" in args.values else None
    )
    fixture_path = args.get("fixture")
    if not fixture_path:
        cli.fail("Error: --fixture is required")
    if not Path(fixture_path).is_file():
        cli.fail(f"Fixture not found: {fixture_path}")
    content = Path(args.get("content-dir")) if args.get("content-dir") else content_dir()
    if not content.is_dir():
        cli.fail(f"Content directory not found: {content}")
    fail_on_regression = "fail" in args.flags
    baseline_path = args.get("baseline")
    if fail_on_regression and not baseline_path:
        cli.fail("Error: --fail-on-regression requires --baseline")
    executable = Path(sys.argv[0]).resolve().parent / "search"
    if not (executable.is_file() and os.access(executable, os.X_OK)):
        cli.fail(f"Search command is not executable: {executable}")
    raw = Path(fixture_path).read_bytes()
    try:
        fixture = json.loads(raw)
    except ValueError:
        fixture = None
    if not valid_fixture(fixture):
        cli.fail("Invalid retrieval fixture: expected version 1 question format")
    role = fixture.get("evaluation_role") or "unspecified"
    validate_locators(content, fixture)
    shas = (hashlib.sha256(raw).hexdigest(), corpus_sha(content))
    cases = []
    for case in fixture["cases"]:
        runs = []
        for label, limit in (("Full-ranking", 0), ("Bounded top-five", 5)):
            out, err, status, elapsed = _search(executable, content, case, limit, max_bytes)
            if status:
                text = err.decode("utf-8", errors="replace").rstrip("\n")
                print(f"{label} retrieval failed for case '{case['id']}':", file=sys.stderr)
                if text:
                    print("\n".join(f"  {line}" for line in text.split("\n")), file=sys.stderr)
                return 1
            try:
                document = json.loads(out)
            except ValueError:
                document = None
            if not (isinstance(document, dict) and isinstance(document.get("results"), list)):
                cli.fail(f"Invalid search JSON for case '{case['id']}'")
            runs.append((document, len(out), elapsed))
        (full, full_size, full_ms), (bounded, bounded_size, bounded_ms) = runs
        cases.append(
            case_record(case, full, bounded, (full_size, bounded_size), (full_ms, bounded_ms))
        )
    current = report(fixture, cases, shas, role)
    if write := args.get("write-baseline"):
        directory = Path(write).parent
        if not directory.is_dir():
            cli.fail(f"Baseline directory not found: {directory}")
        platform.write_text(Path(write), _dump(baseline(current), indent=2) + "\n")
    if baseline_path:
        if not Path(baseline_path).is_file():
            cli.fail(f"Baseline not found: {baseline_path}")
        try:
            frozen = json.loads(Path(baseline_path).read_bytes())
        except ValueError:
            frozen = None
        ids = (
            [case.get("id") for case in frozen.get("cases", [])]
            if isinstance(frozen, dict) and isinstance(frozen.get("cases"), list)
            else None
        )
        if not (
            isinstance(frozen, dict)
            and frozen.get("format") == "knowledge-base-retrieval-evaluation-baseline"
            and frozen.get("version") == 1
            and frozen.get("fixture_id") == fixture["fixture_id"]
            and ids is not None
            and len(ids) == len({json.dumps(i) for i in ids})
        ):
            cli.fail("Invalid retrieval baseline: expected version 1 baseline format")
        current["baseline_comparison"] = compare(current, frozen)
    print(_dump(current, indent=2))
    if fail_on_regression:
        comparison = current["baseline_comparison"]
        if comparison["regressions"] or not (
            comparison["fixture_match"]
            and comparison["corpus_match"]
            and comparison["evaluation_role_match"]
        ):
            return 1
    return 0
