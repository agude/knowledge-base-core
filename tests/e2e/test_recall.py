"""End-to-end tests for `kb recall` over curated knowledge."""

import pytest

from .harness import Kb

pytestmark = pytest.mark.xfail(strict=True, reason="kb recall is not implemented yet")

NAS_RESTART = (
    "knowledge/infra/nas.md#1 | Restart order | fresh, verified 2026-08-16 | 1 source\n"
    "## Restart order\n"
    "\n"
    "Traefik first, then Syncthing, then Plex.\n"
    "\n"
    "knowledge/infra/syncthing.md#2 | Restart order | fresh, verified 2026-10-20 | 0 sources\n"
    "## Restart order\n"
    "\n"
    "Restart Syncthing after Traefik, and before Plex.\n"
    "\n"
    "Uncurated (pending, not yet verified):\n"
    "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 | NAS restart after the update\n"
    "Read with: kb read <locator>\n"
)
NAS_RESTART_LIMIT_ONE = (
    "knowledge/infra/nas.md#1 | Restart order | fresh, verified 2026-08-16 | 1 source\n"
    "## Restart order\n"
    "\n"
    "Traefik first, then Syncthing, then Plex.\n"
    "\n"
    "Also relevant:\n"
    "  knowledge/infra/syncthing.md#2 | Restart order\n"
    "Uncurated (pending, not yet verified):\n"
    "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 | NAS restart after the update\n"
    "Read with: kb read <locator>\n"
)
SYNCTHING_ONLY = (
    "knowledge/infra/syncthing.md#2 | Restart order | fresh, verified 2026-10-20 | 0 sources\n"
    "## Restart order\n"
    "\n"
    "Restart Syncthing after Traefik, and before Plex.\n"
    "\n"
    "Read with: kb read <locator>\n"
)


def test_returns_qualifying_sections_in_full(kb: Kb) -> None:
    result = kb("recall", "nas", "restart", "order")
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == NAS_RESTART


def test_one_quoted_argument_is_the_same_query(kb: Kb) -> None:
    assert kb("recall", "nas restart order").stdout == NAS_RESTART


def test_limit_returns_the_rest_as_also_relevant(kb: Kb) -> None:
    result = kb("recall", "--limit", "1", "nas", "restart", "order")
    assert result.returncode == 0
    assert result.stdout == NAS_RESTART_LIMIT_ONE


def test_in_restricts_the_search_to_a_file(kb: Kb) -> None:
    result = kb("recall", "--in", "knowledge/infra/syncthing.md", "nas", "restart", "order")
    assert result.returncode == 0
    assert result.stdout == SYNCTHING_ONLY


def test_no_match_prints_one_line(kb: Kb) -> None:
    result = kb("recall", "quantum", "zebra")
    assert result.returncode == 0
    assert result.stdout == 'No curated knowledge matches "quantum zebra".\n'


def test_stopwords_only_match_nothing(kb: Kb) -> None:
    result = kb("recall", "the", "and", "of")
    assert result.returncode == 0
    assert result.stdout == 'No curated knowledge matches "the and of".\n'


def test_missing_query_prints_usage(kb: Kb) -> None:
    result = kb("recall")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Usage: kb recall QUERY... [--limit N] [--in PATH]\n"


@pytest.mark.parametrize("limit", ["0", "x"])
def test_limit_must_be_a_positive_integer(kb: Kb, limit: str) -> None:
    result = kb("recall", "--limit", limit, "nas")
    assert result.returncode == 1
    assert result.stderr == "Option --limit must be a positive integer\n"


def test_limit_requires_a_value(kb: Kb) -> None:
    result = kb("recall", "nas", "--limit")
    assert result.returncode == 1
    assert result.stderr == "Option --limit requires an argument\n"


def test_unknown_option_is_a_usage_error(kb: Kb) -> None:
    result = kb("recall", "nas", "--bogus")
    assert result.returncode == 1
    assert result.stderr == "Unknown option: --bogus\n"


def test_in_must_name_an_existing_path(kb: Kb) -> None:
    result = kb("recall", "--in", "knowledge/nope", "nas")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "kb recall: no such path: knowledge/nope\n"


def test_help_names_the_command(kb: Kb) -> None:
    result = kb("recall", "--help")
    assert result.returncode == 0
    assert result.stdout.startswith("Usage: kb recall")


def test_archived_evidence_is_not_searched_when_curated_results_exist(kb: Kb) -> None:
    result = kb("recall", "nas", "restart", "order")
    assert "knowledge/infra/nas.md#1 | Restart order" in result.stdout
    assert "observations/archived/" not in result.stdout
