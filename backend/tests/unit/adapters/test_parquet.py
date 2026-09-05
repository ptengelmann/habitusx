from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from habitusx.adapters.parquet import SCHEMA, read_records, to_record, write_observations
from habitusx.domain.attribution import Attribution, Confidence, Evidence, SignalType
from habitusx.domain.observations import CommitObservation
from habitusx.domain.reverts import RevertInfo
from tests.fakes import SHA_A, SHA_B


def observation(**overrides: object) -> CommitObservation:
    base: dict[str, object] = {
        "day": date(2025, 9, 1),
        "registry_version": 1,
        "event_id": "1",
        "repo": "octo/repo",
        "sha": SHA_A,
        "pushed_at": datetime(2025, 9, 1, 12, tzinfo=UTC),
        "is_distinct": True,
        "push_size": 3,
        "subject": "Add retry",
        "message": "Add retry\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        "is_revert": False,
        "revert": None,
        "author_email_hash": "abc",
        "author_name_hash": None,
        "pusher_login_hash": "def",
        "pusher_is_bot": False,
        "attribution": Attribution(
            agent_id="claude-code",
            confidence=Confidence.HIGH,
            evidence=(
                Evidence(
                    agent_id="claude-code",
                    signal_id="claude-code-coauthor-email",
                    signal_type=SignalType.TRAILER_EMAIL,
                    confidence=Confidence.HIGH,
                    matched="noreply@anthropic.com",
                ),
            ),
        ),
        "agent_id": "claude-code",
        "matched_prefilter": True,
        "commits_in_repo_day": 7,
    }
    base.update(overrides)
    return CommitObservation.model_validate(base)


def test_schema_and_record_keys_agree() -> None:
    assert set(to_record(observation())) == set(SCHEMA.names)


def test_roundtrip_preserves_values_and_nulls(tmp_path: Path) -> None:
    attributed = observation()
    revert = observation(
        event_id="2",
        sha=SHA_B,
        subject='Revert "Add retry (#12)" (#15)',
        message=f'Revert "Add retry (#12)" (#15)\n\nThis reverts commit {SHA_A}.',
        is_revert=True,
        revert=RevertInfo(
            is_reapply=False,
            original_subject="Add retry (#12)",
            reverted_sha=SHA_A,
            original_pr_number=12,
            revert_pr_number=15,
        ),
        attribution=None,
        agent_id=None,
        matched_prefilter=False,
        push_size=None,
        pusher_is_bot=True,
    )
    path = tmp_path / "day=2025-09-01" / "commits.parquet"
    assert write_observations([attributed, revert], path) == 2

    rows = read_records(path)
    assert len(rows) == 2
    a, r = rows
    assert a["agent_id"] == "claude-code"
    assert a["attribution_confidence"] == "high"
    assert json.loads(a["evidence_json"])[0]["matched"] == "noreply@anthropic.com"
    assert a["pushed_at"] == datetime(2025, 9, 1, 12, tzinfo=UTC)
    assert a["day"] == date(2025, 9, 1)
    assert r["agent_id"] is None
    assert r["evidence_json"] is None
    assert r["push_size"] is None
    assert r["is_revert"] is True
    assert r["reverted_sha"] == SHA_A
    assert r["original_pr_number"] == 12
    assert r["revert_pr_number"] == 15
    assert r["pusher_is_bot"] is True


def test_writes_empty_file_with_schema(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    assert write_observations([], path) == 0
    assert read_records(path) == []
