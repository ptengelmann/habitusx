"""BigQuery adapter for GitHub Archive."""

from habitusx.adapters.bigquery.gateway import (
    BigQueryClientLike,
    BigQueryGateway,
    QueryJobLike,
    QueryResult,
    QueryStats,
    make_client,
)
from habitusx.adapters.bigquery.queries import (
    RenderedQuery,
    active_repos_for_day,
    commits_for_day,
    table_for_day,
)

__all__ = [
    "BigQueryClientLike",
    "BigQueryGateway",
    "QueryJobLike",
    "QueryResult",
    "QueryStats",
    "RenderedQuery",
    "active_repos_for_day",
    "commits_for_day",
    "make_client",
    "table_for_day",
]
