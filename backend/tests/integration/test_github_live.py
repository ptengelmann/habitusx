"""Live check against the GitHub GraphQL API. Costs a few points, no money.

Run with:  HABITUSX_RUN_INTEGRATION=1 uv run pytest -m integration

Proves what unit tests cannot: the rendered query is valid GraphQL for the real schema,
the token works, and the response shape matches the parser.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from habitusx.adapters.github import GitHubGraphQL, HttpxTransport, fetch_activity
from habitusx.adapters.github.client import TokenSource
from habitusx.config import get_settings
from habitusx.domain.panel_observations import FetchStatus

pytestmark = pytest.mark.integration


def test_fetch_two_public_repos_and_one_that_does_not_exist() -> None:
    token = TokenSource(env_token=get_settings().github_token).resolve()
    client = GitHubGraphQL(HttpxTransport(token), wait_for_reset=False)
    since = datetime.now(UTC) - timedelta(days=30)

    results = fetch_activity(
        client,
        ["anthropics/anthropic-sdk-python", "python/cpython", "habitusx-does-not-exist/nope"],
        since=since,
        batch_size=3,
    )
    by_repo = {r.repo: r for r in results}
    assert by_repo["anthropics/anthropic-sdk-python"].status is FetchStatus.OK
    assert by_repo["python/cpython"].status is FetchStatus.OK
    assert by_repo["habitusx-does-not-exist/nope"].status is FetchStatus.NOT_FOUND
    cpython = by_repo["python/cpython"]
    assert cpython.primary_language == "Python"
    assert cpython.commits, "cpython has commits every month"
    assert all(c.committed_at >= since for c in cpython.commits)
    assert client.last_rate_limit is not None
    assert client.points_spent > 0
