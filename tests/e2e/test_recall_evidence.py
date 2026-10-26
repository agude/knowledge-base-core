"""End-to-end tests for the evidence parts of `kb recall`."""

import pytest

from .harness import Kb

pytestmark = pytest.mark.xfail(strict=True, reason="recall evidence is not implemented yet")


def test_no_curated_match_lists_archived_evidence(kb: Kb) -> None:
    result = kb("recall", "label", "printer", "driver")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "label printer driver".\n'
        "Evidence:\n"
        "  observations/archived/20260615T083000-9a8b7c6d.md | 2026-06-15 | observation "
        "| Old label printer note\n"
        "Read with: kb read <locator>\n"
    )


def test_transcript_evidence_shows_the_best_matching_line(kb: Kb) -> None:
    result = kb("recall", "outage", "start", "services", "order")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "outage start services order".\n'
        "Evidence:\n"
        "  observations/archived/20260903T120000-c3d4e5f6.md | 2026-09-03 | transcript "
        "| After the outage, what order should the services start in?\n"
        "Read with: kb read <locator>\n"
    )


def test_open_question_is_evidence_with_its_kind(kb: Kb) -> None:
    result = kb("recall", "backup", "disk", "owner")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "backup disk owner".\n'
        "Evidence:\n"
        "  questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open question "
        "| Who owns the backup disk?\n"
        "Read with: kb read <locator>\n"
    )


def test_pending_observation_is_evidence_when_nothing_curated_matches(kb: Kb) -> None:
    result = kb("recall", "firmware", "restarted", "plex")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "firmware restarted plex".\n'
        "Evidence:\n"
        "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 | observation "
        "| NAS restart after the update\n"
        "Read with: kb read <locator>\n"
    )


def test_uncurated_pending_transcript_shows_its_matching_line(kb: Kb) -> None:
    result = kb("recall", "family", "share")
    assert result.returncode == 0
    assert result.stdout == (
        "knowledge/infra/syncthing.md#1 | Folder layout | fresh, verified 2026-10-20 | 0 sources\n"
        "## Folder layout\n"
        "\n"
        "The family share is /srv/sync/family, one folder per family member.\n"
        "\n"
        "Uncurated (pending, not yet verified):\n"
        "  observations/pending/20261025T180000-1f2e3d4c.md | 2026-10-25 "
        "| Which folder does the family share use on the NAS?\n"
        "Read with: kb read <locator>\n"
    )
