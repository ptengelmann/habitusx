from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from habitusx.adapters.github.client import (
    GitHubAPIError,
    GitHubGraphQL,
    GraphQLResponse,
    HttpxTransport,
    RateLimitExhaustedError,
    RateLimitInfo,
    TokenSource,
)
from tests.fakes import FakeTransport, gql_repo, gql_response


class TestGraphQLResponse:
    def test_error_paths_maps_alias_to_type(self) -> None:
        body = gql_response({"r0": gql_repo(), "r1": None})
        response = GraphQLResponse(data=body["data"], errors=tuple(body["errors"]), rate_limit=None)
        assert response.error_paths() == {"r1": "NOT_FOUND"}

    def test_rate_limit_parses_iso_z(self) -> None:
        info = RateLimitInfo.from_json(
            {"cost": 3, "remaining": 100, "resetAt": "2026-09-05T13:00:00Z"}
        )
        assert info.reset_at == datetime(2026, 9, 5, 13, tzinfo=UTC)


class TestGitHubGraphQL:
    def test_execute_tracks_points_and_keeps_partial_errors(self) -> None:
        transport = FakeTransport(
            [gql_response({"r0": gql_repo(), "r1": None}, cost=4, remaining=4000)]
        )
        client = GitHubGraphQL(transport, sleep=lambda _s: None)
        response = client.execute("query", {"since": "x"})
        assert response.data["r0"]["nameWithOwner"] == "octo/repo"
        assert response.error_paths() == {"r1": "NOT_FOUND"}
        assert client.points_spent == 4
        assert client.requests_made == 1
        assert client.last_rate_limit is not None
        assert client.last_rate_limit.remaining == 4000

    def test_whole_query_failure_raises(self) -> None:
        transport = FakeTransport([{"errors": [{"type": "FORBIDDEN", "message": "bad token"}]}])
        with pytest.raises(GitHubAPIError, match="FORBIDDEN"):
            GitHubGraphQL(transport).execute("q", {})

    def test_waits_for_reset_when_below_reserve(self) -> None:
        slept: list[float] = []
        now = datetime(2026, 9, 5, 12, 59, tzinfo=UTC)
        transport = FakeTransport(
            [
                gql_response({"r0": gql_repo()}, remaining=150, reset_at="2026-09-05T13:00:00Z"),
                gql_response({"r0": gql_repo()}, remaining=4999, reset_at="2026-09-05T14:00:00Z"),
            ]
        )
        client = GitHubGraphQL(transport, reserve_points=200, sleep=slept.append, now=lambda: now)
        client.execute("q", {})
        client.execute("q", {})  # second call must pause first
        assert len(slept) == 1
        assert 60 <= slept[0] <= 63  # until reset plus a 2s margin

    def test_raises_instead_of_waiting_when_disabled(self) -> None:
        transport = FakeTransport([gql_response({"r0": gql_repo()}, remaining=10)])
        client = GitHubGraphQL(transport, reserve_points=200, wait_for_reset=False)
        client.execute("q", {})
        with pytest.raises(RateLimitExhaustedError, match="10 points left"):
            client.execute("q", {})


class TestHttpxTransport:
    def _transport(
        self, handler: Callable[[httpx.Request], httpx.Response], attempts: int = 3
    ) -> HttpxTransport:
        t = HttpxTransport("tok", max_attempts=attempts, sleep=lambda _s: None)
        t._client = httpx.Client(transport=httpx.MockTransport(handler), headers=t._client.headers)
        return t

    def test_retries_502_then_succeeds(self) -> None:
        statuses = iter([502, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            status = next(statuses)
            assert request.headers["Authorization"] == "bearer tok"
            return httpx.Response(status, json={"data": {"ok": True}} if status == 200 else None)

        assert self._transport(handler).post("q", {}) == {"data": {"ok": True}}

    def test_does_not_retry_401(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(401, text="Bad credentials")

        with pytest.raises(GitHubAPIError, match="401") as excinfo:
            self._transport(handler).post("q", {})
        assert excinfo.value.status == 401
        assert calls == 1

    def test_gives_up_after_max_attempts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        with pytest.raises(GitHubAPIError, match="after 2 attempts"):
            self._transport(handler, attempts=2).post("q", {})

    def test_requires_token(self) -> None:
        with pytest.raises(GitHubAPIError, match="token is required"):
            HttpxTransport("")


class TestTokenSource:
    def test_env_wins(self) -> None:
        assert TokenSource(env_token="env", cli_lookup=lambda: "cli").resolve() == "env"  # noqa: S106

    def test_falls_back_to_cli(self) -> None:
        assert TokenSource(env_token=None, cli_lookup=lambda: "cli").resolve() == "cli"

    def test_error_when_neither(self) -> None:
        with pytest.raises(GitHubAPIError, match="HABITUSX_GITHUB_TOKEN"):
            TokenSource(env_token=None, cli_lookup=lambda: None).resolve()
