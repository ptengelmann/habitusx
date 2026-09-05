from __future__ import annotations

import pytest

from habitusx.adapters.bigquery.gateway import BigQueryGateway
from habitusx.adapters.bigquery.queries import RenderedQuery
from habitusx.errors import HabitusXError, QueryBudgetExceededError
from tests.fakes import FakeClient, fake_job_config

QUERY = RenderedQuery(name="probe", sql="SELECT 1", params={"p": "v"})


def make_gateway(client: FakeClient, max_bytes: int = 1000) -> BigQueryGateway:
    return BigQueryGateway(
        client, max_bytes_billed=max_bytes, location="US", job_config_factory=fake_job_config
    )


class TestEstimate:
    def test_returns_dry_run_bytes_and_binds_params(self) -> None:
        client = FakeClient(estimate_bytes=500)
        assert make_gateway(client).estimate(QUERY) == 500
        assert len(client.calls) == 1
        cfg = client.calls[0]["job_config"]
        assert cfg.dry_run is True
        assert cfg.maximum_bytes_billed is None
        assert cfg.params == {"p": "v"}
        assert client.calls[0]["location"] == "US"


class TestRun:
    def test_over_budget_raises_before_running(self) -> None:
        client = FakeClient(estimate_bytes=5_000, rows=[{"x": 1}])
        with pytest.raises(QueryBudgetExceededError) as excinfo:
            make_gateway(client, max_bytes=1_000).run(QUERY)
        assert excinfo.value.estimated_bytes == 5_000
        assert excinfo.value.limit_bytes == 1_000
        assert excinfo.value.query_name == "probe"
        assert isinstance(excinfo.value, HabitusXError)
        assert len(client.calls) == 1, "must not submit the real query"

    def test_exactly_at_budget_runs(self) -> None:
        client = FakeClient(estimate_bytes=1_000, rows=[{"x": 1}])
        result = make_gateway(client, max_bytes=1_000).run(QUERY)
        assert result.rows == [{"x": 1}]

    def test_real_run_passes_ceiling_to_server_and_returns_stats(self) -> None:
        client = FakeClient(estimate_bytes=400, rows=[{"a": 1}, {"a": 2}], billed_bytes=512)
        result = make_gateway(client, max_bytes=1000).run(QUERY)
        assert [c["job_config"].dry_run for c in client.calls] == [True, False]
        assert client.calls[1]["job_config"].maximum_bytes_billed == 1000
        assert result.rows == [{"a": 1}, {"a": 2}]
        s = result.stats
        assert (s.query_name, s.estimated_bytes, s.billed_bytes, s.slot_millis, s.job_id) == (
            "probe",
            400,
            512,
            1234,
            "job-fake-1",
        )
        assert s.sql_hash == QUERY.sql_hash
        assert s.elapsed_seconds >= 0

    def test_rows_are_plain_dicts(self) -> None:
        client = FakeClient(estimate_bytes=1, rows=[{"k": "v"}])
        row = make_gateway(client).run(QUERY).rows[0]
        assert type(row) is dict


def test_rejects_nonpositive_ceiling() -> None:
    with pytest.raises(ValueError, match="positive"):
        BigQueryGateway(FakeClient(estimate_bytes=1), max_bytes_billed=0)
