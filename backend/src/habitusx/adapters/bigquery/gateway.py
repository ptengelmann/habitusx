"""Run queries against BigQuery with a hard cost ceiling.

Every query goes through two steps: a dry run to estimate bytes, checked against the
ceiling before anything is spent, and then the real run with the same ceiling passed to
BigQuery as ``maximum_bytes_billed`` so the server enforces it too. The vendor SDK is
behind a :class:`typing.Protocol`, which is what lets the services layer be tested with an
in-memory fake.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from habitusx.errors import QueryBudgetExceededError
from habitusx.logging import get_logger

if TYPE_CHECKING:
    from habitusx.adapters.bigquery.queries import RenderedQuery

log = get_logger(__name__)


class QueryJobLike(Protocol):
    """The subset of ``google.cloud.bigquery.QueryJob`` we rely on."""

    @property
    def total_bytes_processed(self) -> int | None:
        """Bytes the query read, or would read for a dry run."""
        ...

    @property
    def total_bytes_billed(self) -> int | None:
        """Bytes actually billed; ``None`` for dry runs."""
        ...

    @property
    def slot_millis(self) -> int | None:
        """Slot-milliseconds consumed."""
        ...

    @property
    def job_id(self) -> str | None:
        """Server-side job identifier, useful for audit."""
        ...

    def result(self) -> Iterable[Mapping[str, Any]]:
        """Iterate result rows once the job completes."""
        ...


class BigQueryClientLike(Protocol):
    """The subset of ``google.cloud.bigquery.Client`` we rely on."""

    def query(
        self,
        query: str,
        *,
        job_config: Any = None,  # noqa: ANN401 - vendor config type; Any keeps the Protocol satisfiable
        location: str | None = None,
    ) -> QueryJobLike:
        """Submit ``query`` and return the job handle."""
        ...


JobConfigFactory = Callable[[bool, int | None, Mapping[str, str]], object]
"""Builds a vendor job config from (dry_run, maximum_bytes_billed, string params)."""


@dataclass(frozen=True, slots=True)
class QueryStats:
    """What a query cost and how long it took."""

    query_name: str
    sql_hash: str
    estimated_bytes: int
    billed_bytes: int
    slot_millis: int
    elapsed_seconds: float
    job_id: str | None


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Rows as plain dicts plus the stats that produced them."""

    rows: list[dict[str, Any]]
    stats: QueryStats


def _default_job_config(
    dry_run: bool, maximum_bytes_billed: int | None, params: Mapping[str, str]
) -> object:
    from google.cloud import bigquery  # noqa: PLC0415 - vendor import kept local to the adapter

    config = bigquery.QueryJobConfig(
        dry_run=dry_run,
        use_query_cache=not dry_run,
        query_parameters=[
            bigquery.ScalarQueryParameter(name, "STRING", value) for name, value in params.items()
        ],
    )
    # Setting this to None serialises as the string "None" and BigQuery rejects the job,
    # so it is only assigned when there is a real ceiling (never on dry runs).
    if maximum_bytes_billed is not None:
        config.maximum_bytes_billed = maximum_bytes_billed
    return config


def make_client(project: str, location: str) -> BigQueryClientLike:
    """Construct the real client using Application Default Credentials."""
    from google.cloud import bigquery  # noqa: PLC0415 - vendor import kept local to the adapter

    return bigquery.Client(project=project, location=location)


class BigQueryGateway:
    """Dry-run, budget-check, run. Nothing else."""

    def __init__(
        self,
        client: BigQueryClientLike,
        *,
        max_bytes_billed: int,
        location: str = "US",
        job_config_factory: JobConfigFactory = _default_job_config,
    ) -> None:
        """Bind to a client and a per-query byte ceiling."""
        if max_bytes_billed < 1:
            msg = "max_bytes_billed must be positive"
            raise ValueError(msg)
        self._client = client
        self._max_bytes = max_bytes_billed
        self._location = location
        self._job_config = job_config_factory

    @property
    def max_bytes_billed(self) -> int:
        """The per-query ceiling this gateway enforces."""
        return self._max_bytes

    def estimate(self, query: RenderedQuery) -> int:
        """Dry-run ``query`` and return the bytes it would process. Spends nothing."""
        job = self._client.query(
            query.sql,
            job_config=self._job_config(True, None, query.params),
            location=self._location,
        )
        estimated = job.total_bytes_processed or 0
        log.info("bigquery.dry_run", query=query.name, estimated_bytes=estimated)
        return estimated

    def run(self, query: RenderedQuery) -> QueryResult:
        """Execute ``query`` if its estimate fits the ceiling.

        Raises:
            QueryBudgetExceededError: if the dry-run estimate exceeds ``max_bytes_billed``.
        """
        estimated = self.estimate(query)
        if estimated > self._max_bytes:
            raise QueryBudgetExceededError(estimated, self._max_bytes, query.name)

        started = time.perf_counter()
        job = self._client.query(
            query.sql,
            job_config=self._job_config(False, self._max_bytes, query.params),
            location=self._location,
        )
        rows = [dict(row.items()) for row in job.result()]
        elapsed = time.perf_counter() - started

        stats = QueryStats(
            query_name=query.name,
            sql_hash=query.sql_hash,
            estimated_bytes=estimated,
            billed_bytes=job.total_bytes_billed or 0,
            slot_millis=job.slot_millis or 0,
            elapsed_seconds=round(elapsed, 3),
            job_id=job.job_id,
        )
        log.info(
            "bigquery.run",
            query=query.name,
            rows=len(rows),
            billed_bytes=stats.billed_bytes,
            elapsed_seconds=stats.elapsed_seconds,
            job_id=stats.job_id,
        )
        return QueryResult(rows=rows, stats=stats)
