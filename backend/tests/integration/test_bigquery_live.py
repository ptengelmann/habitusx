"""Live checks against BigQuery. Dry runs only, so they cost nothing.

Run with:  HABITUSX_RUN_INTEGRATION=1 HABITUSX_GCP_PROJECT=<id> uv run pytest -m integration

What they prove that unit tests cannot: the SQL parses in BigQuery, every prefilter regex
is accepted by RE2, the day table exists, and the estimate is in the expected range.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from habitusx.adapters.bigquery import BigQueryGateway, commits_for_day, make_client
from habitusx.config import get_settings
from habitusx.domain.prefilter import compile_prefilter
from habitusx.registry import load_registry

pytestmark = pytest.mark.integration

GIB = 1024**3


@pytest.fixture(scope="module")
def gateway() -> BigQueryGateway:
    settings = get_settings()
    if not settings.gcp_project:
        pytest.skip("HABITUSX_GCP_PROJECT not set")
    client = make_client(settings.gcp_project, settings.bq_location)
    return BigQueryGateway(client, max_bytes_billed=settings.bq_max_bytes_billed)


def test_commits_for_day_dry_runs_and_is_affordable(
    gateway: BigQueryGateway, registry_path: Path
) -> None:
    query = commits_for_day(date(2025, 9, 1), compile_prefilter(load_registry(registry_path)))
    estimated = gateway.estimate(query)
    assert 5 * GIB < estimated < 30 * GIB, f"unexpected estimate {estimated:,} bytes"
