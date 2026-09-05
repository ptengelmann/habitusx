"""Thin GraphQL client for api.github.com with retries and rate-limit accounting.

The transport is a :class:`typing.Protocol` so tests can substitute canned responses.
The real transport uses httpx, retries transient failures (502/503/504, 429, network) with
exponential backoff, and never retries 4xx errors that indicate a bad request or token.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from habitusx.errors import HabitusXError
from habitusx.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
USER_AGENT = "habitusx/0.1 (+https://github.com/ptengelmann/habitusx)"
_RETRY_STATUSES = frozenset({429, 502, 503, 504})


class GitHubAPIError(HabitusXError):
    """The GitHub API could not be used: auth failure, persistent 5xx, or malformed reply."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        """Record the HTTP status when there was one."""
        self.status = status
        super().__init__(message)


class RateLimitExhaustedError(HabitusXError):
    """Fewer GraphQL points remain than the configured reserve, and waiting was disabled."""

    def __init__(self, remaining: int, reset_at: datetime) -> None:
        """Say how many points remain and when the window resets."""
        self.remaining = remaining
        self.reset_at = reset_at
        super().__init__(
            f"GitHub GraphQL rate limit nearly exhausted ({remaining} points left); "
            f"resets at {reset_at.isoformat()}. Re-run after that or allow waiting."
        )


class GraphQLTransport(Protocol):
    """Send one GraphQL request and return the decoded JSON body."""

    def post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST ``{query, variables}`` and return the parsed response body."""
        ...


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """The ``rateLimit`` block GitHub returns when asked for it."""

    cost: int
    remaining: int
    reset_at: datetime

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RateLimitInfo:
        """Parse the JSON object under ``data.rateLimit``."""
        return cls(
            cost=int(data["cost"]),
            remaining=int(data["remaining"]),
            reset_at=datetime.fromisoformat(str(data["resetAt"]).replace("Z", "+00:00")),
        )


@dataclass(frozen=True, slots=True)
class GraphQLResponse:
    """One response, with per-alias errors kept rather than raised."""

    data: dict[str, Any]
    errors: tuple[dict[str, Any], ...]
    rate_limit: RateLimitInfo | None

    def error_paths(self) -> dict[str, str]:
        """Map the first path segment (our alias) of each error to its type, e.g. NOT_FOUND."""
        out: dict[str, str] = {}
        for err in self.errors:
            path = err.get("path") or []
            if path:
                out.setdefault(str(path[0]), str(err.get("type") or err.get("message") or "ERROR"))
        return out


class HttpxTransport:
    """Real transport. Retries transient failures; surfaces everything else as GitHubAPIError."""

    def __init__(
        self,
        token: str,
        *,
        url: str = GITHUB_GRAPHQL_URL,
        timeout_seconds: float = 60.0,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create an authenticated client. ``sleep`` is injectable for tests."""
        if not token:
            msg = "a GitHub token is required"
            raise GitHubAPIError(msg)
        self._client = httpx.Client(
            base_url="",
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )
        self._url = url
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep

    def post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST with retries on 429/5xx and network errors."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.post(
                    self._url, json={"query": query, "variables": variables}
                )
            except httpx.HTTPError as exc:
                last_error = exc
                log.warning("github.transport_error", attempt=attempt, error=str(exc))
            else:
                if response.status_code == 200:
                    body: dict[str, Any] = response.json()
                    return body
                if response.status_code in _RETRY_STATUSES:
                    last_error = GitHubAPIError(
                        f"GitHub returned {response.status_code}", status=response.status_code
                    )
                    log.warning(
                        "github.retryable_status", attempt=attempt, status=response.status_code
                    )
                else:
                    snippet = response.text[:300]
                    raise GitHubAPIError(
                        f"GitHub returned {response.status_code}: {snippet}",
                        status=response.status_code,
                    )
            if attempt < self._max_attempts:
                self._sleep(min(30.0, (2**attempt) + random.uniform(0, 1)))  # noqa: S311 - jitter, not security
        raise GitHubAPIError(
            f"GitHub GraphQL failed after {self._max_attempts} attempts: {last_error}"
        )


class GitHubGraphQL:
    """Execute queries, track the point budget, and pause or fail when it runs low."""

    def __init__(
        self,
        transport: GraphQLTransport,
        *,
        reserve_points: int = 200,
        wait_for_reset: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bind to a transport. ``reserve_points`` is never spent; below it we wait or fail."""
        self._transport = transport
        self._reserve = reserve_points
        self._wait = wait_for_reset
        self._sleep = sleep
        self._now = now
        self.last_rate_limit: RateLimitInfo | None = None
        self.points_spent = 0
        self.requests_made = 0

    def execute(self, query: str, variables: dict[str, Any]) -> GraphQLResponse:
        """Run one query. Partial per-alias errors are returned, transport errors raised."""
        self._respect_budget()
        body = self._transport.post(query, variables)
        data = body.get("data") or {}
        errors = tuple(body.get("errors") or ())
        if not data and errors:
            # No data at all means the whole query failed (syntax, auth, or hard rate limit).
            first = errors[0]
            raise GitHubAPIError(
                f"GraphQL query failed: {first.get('type')}: {first.get('message')}"
            )
        rate_limit = RateLimitInfo.from_json(data["rateLimit"]) if data.get("rateLimit") else None
        if rate_limit:
            self.last_rate_limit = rate_limit
            self.points_spent += rate_limit.cost
        self.requests_made += 1
        return GraphQLResponse(data=data, errors=errors, rate_limit=rate_limit)

    def _respect_budget(self) -> None:
        info = self.last_rate_limit
        if info is None or info.remaining > self._reserve:
            return
        if not self._wait:
            raise RateLimitExhaustedError(info.remaining, info.reset_at)
        delay = max(0.0, (info.reset_at - self._now()).total_seconds()) + 2.0
        log.warning("github.rate_limit_wait", remaining=info.remaining, sleep_seconds=round(delay))
        self._sleep(delay)
        self.last_rate_limit = None


@dataclass(slots=True)
class TokenSource:
    """Resolve a GitHub token from the environment or the gh CLI."""

    env_token: str | None = None
    cli_lookup: Callable[[], str | None] | None = field(default=None)

    def resolve(self) -> str:
        """Environment first, then ``gh auth token``. Raises GitHubAPIError if neither works."""
        if self.env_token:
            return self.env_token
        token = (self.cli_lookup or token_from_gh_cli)()
        if not token:
            raise GitHubAPIError(
                "No GitHub token. Set HABITUSX_GITHUB_TOKEN (a fine-grained token with public "
                "repository read access) or log in with `gh auth login`."
            )
        return token


def token_from_gh_cli() -> str | None:
    """Return the token the gh CLI is logged in with, or ``None`` if unavailable."""
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, no user input
            [gh, "auth", "token"], capture_output=True, text=True, check=False, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    return token or None
