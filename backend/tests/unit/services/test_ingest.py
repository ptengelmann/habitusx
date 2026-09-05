from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from habitusx.adapters.bigquery.gateway import BigQueryGateway
from habitusx.adapters.parquet import read_records
from habitusx.domain.attribution import AttributionEngine
from habitusx.domain.observations import METHODOLOGY_VERSION, hash_identity
from habitusx.errors import QueryBudgetExceededError
from habitusx.registry import load_registry
from habitusx.services.ingest import build_observation, estimate_day, ingest_day, output_dir
from tests.fakes import SHA_A, SHA_B, FakeClient, fake_job_config, sample_rows, warehouse_row

DAY = date(2025, 9, 1)


def gateway(client: FakeClient, max_bytes: int = 10**12) -> BigQueryGateway:
    return BigQueryGateway(client, max_bytes_billed=max_bytes, job_config_factory=fake_job_config)


class TestBuildObservation:
    def test_attributed_commit(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        engine = AttributionEngine(registry)
        row = sample_rows()[0]
        obs = build_observation(row, day=DAY, engine=engine, registry_version=registry.version)
        assert obs is not None
        assert obs.agent_id == "claude-code"
        assert obs.attribution is not None
        assert obs.attribution.confidence.value == "high"
        assert obs.matched_prefilter is True
        assert obs.is_revert is False
        assert obs.subject == "Add retry"
        assert obs.methodology_version == METHODOLOGY_VERSION
        # Identities never stored raw.
        assert obs.author_email_hash == hash_identity("octo@example.com")
        assert "octo@example.com" not in obs.model_dump_json()
        assert obs.pusher_is_bot is False

    def test_revert_by_bot_pusher(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        engine = AttributionEngine(registry)
        obs = build_observation(
            sample_rows()[1], day=DAY, engine=engine, registry_version=registry.version
        )
        assert obs is not None
        assert obs.is_revert is True
        assert obs.revert is not None
        assert obs.revert.reverted_sha == SHA_A
        assert obs.revert.original_pr_number == 12
        assert obs.revert.revert_pr_number == 15
        assert obs.pusher_is_bot is True
        # The pushing bot is a registry signal, so the revert itself is attributed to Copilot.
        assert obs.agent_id == "github-copilot"

    def test_baseline_commit(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        obs = build_observation(
            sample_rows()[2],
            day=DAY,
            engine=AttributionEngine(registry),
            registry_version=registry.version,
        )
        assert obs is not None
        assert obs.agent_id is None
        assert obs.matched_prefilter is False
        assert obs.is_revert is False

    def test_invalid_row_returns_none(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        assert (
            build_observation(
                sample_rows()[3],
                day=DAY,
                engine=AttributionEngine(registry),
                registry_version=registry.version,
            )
            is None
        )

    def test_hash_identity_is_normalised_and_stable(self) -> None:
        assert hash_identity(" Octo@Example.com ") == hash_identity("octo@example.com")
        assert hash_identity(None) is None
        assert hash_identity("") is None
        assert hash_identity("a") != hash_identity("b")


class TestIngestDay:
    def test_writes_parquet_and_manifest(self, registry_path: Path, tmp_path: Path) -> None:
        registry = load_registry(registry_path)
        client = FakeClient(estimate_bytes=16_000, rows=sample_rows(), billed_bytes=16_384)
        summary = ingest_day(DAY, registry=registry, gateway=gateway(client), out_dir=tmp_path)

        assert summary.rows_total == 3
        assert summary.rows_attributed == 2  # claude commit + copilot-pushed revert
        assert summary.rows_reverts == 1
        assert summary.rows_baseline == 1
        assert summary.rows_skipped_invalid == 1
        assert summary.by_agent == {"claude-code": 1, "github-copilot": 1}
        assert summary.output_path == output_dir(tmp_path, DAY) / "commits.parquet"
        assert summary.output_path.exists()

        rows = read_records(summary.output_path)
        assert {r["sha"] for r in rows} == {SHA_A, SHA_B, "c" * 40}
        assert all(r["registry_version"] == registry.version for r in rows)

        manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
        assert manifest["day"] == "2025-09-01"
        assert manifest["rows"] == {
            "total": 3,
            "attributed": 2,
            "reverts": 1,
            "baseline": 1,
            "skipped_invalid": 1,
        }
        assert manifest["by_agent"] == {"claude-code": 1, "github-copilot": 1}
        assert manifest["stats"]["billed_bytes"] == 16_384
        assert manifest["query"]["name"] == "commits_for_day"
        assert set(manifest["query"]["params"]) == {
            "message_prefilter",
            "author_email_prefilter",
            "author_name_prefilter",
            "pusher_login_prefilter",
        }
        assert manifest["methodology_version"] == METHODOLOGY_VERSION

    def test_budget_exceeded_writes_nothing(self, registry_path: Path, tmp_path: Path) -> None:
        registry = load_registry(registry_path)
        client = FakeClient(estimate_bytes=50 * 1024**3, rows=sample_rows())
        with pytest.raises(QueryBudgetExceededError):
            ingest_day(
                DAY, registry=registry, gateway=gateway(client, max_bytes=1024**3), out_dir=tmp_path
            )
        assert not output_dir(tmp_path, DAY).exists()
        assert len(client.calls) == 1

    def test_query_uses_prefilter_from_registry(self, registry_path: Path, tmp_path: Path) -> None:
        registry = load_registry(registry_path)
        client = FakeClient(estimate_bytes=1, rows=[warehouse_row()])
        ingest_day(DAY, registry=registry, gateway=gateway(client), out_dir=tmp_path)
        params = client.calls[1]["job_config"].params
        assert "noreply@anthropic" in params["message_prefilter"]
        assert "githubarchive.day.20250901" in client.calls[1]["sql"]


def test_estimate_day_delegates_to_gateway(registry_path: Path) -> None:
    client = FakeClient(estimate_bytes=4242)
    assert estimate_day(DAY, registry=load_registry(registry_path), gateway=gateway(client)) == 4242
    assert client.calls[0]["job_config"].dry_run is True
