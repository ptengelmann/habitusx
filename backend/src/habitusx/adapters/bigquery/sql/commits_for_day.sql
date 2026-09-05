-- commits_for_day
--
-- Every commit pushed to a public repository on one UTC day that we need downstream:
--   (a) candidates: message, author or pushing actor matches the registry prefilter
--   (b) reverts and reapplies, from any repository, so they can be joined to earlier days
--   (c) baseline: every other commit in a repository that had at least one candidate,
--       so within-repo comparisons are complete for that day
--
-- The table name is rendered by the query loader after validating the date; everything
-- else is a bound parameter. Only the columns used are selected so bytes scanned stay
-- proportional to the payload column, roughly 16 GiB per day in 2025.
--
-- GitHub Archive lists at most 20 commits per push; payload.size is the true count.

WITH pushes AS (
  SELECT
    id                                                    AS event_id,
    repo.name                                             AS repo,
    actor.login                                           AS pusher_login,
    created_at                                            AS pushed_at,
    SAFE_CAST(JSON_VALUE(payload, '$.size') AS INT64)     AS push_size,
    JSON_QUERY_ARRAY(payload, '$.commits')                AS commits
  FROM `{{ table }}`
  WHERE type = 'PushEvent'
),

commits AS (
  SELECT
    p.event_id,
    p.repo,
    p.pusher_login,
    p.pushed_at,
    p.push_size,
    JSON_VALUE(c, '$.sha')                                AS sha,
    JSON_VALUE(c, '$.message')                            AS message,
    JSON_VALUE(c, '$.author.name')                        AS author_name,
    JSON_VALUE(c, '$.author.email')                       AS author_email,
    COALESCE(SAFE_CAST(JSON_VALUE(c, '$.distinct') AS BOOL), TRUE) AS is_distinct
  FROM pushes AS p, UNNEST(p.commits) AS c
),

flagged AS (
  SELECT
    *,
    REGEXP_CONTAINS(message, @message_prefilter)                          AS message_hit,
    REGEXP_CONTAINS(COALESCE(author_email, ''), @author_email_prefilter)  AS author_email_hit,
    REGEXP_CONTAINS(COALESCE(author_name, ''), @author_name_prefilter)    AS author_name_hit,
    REGEXP_CONTAINS(COALESCE(pusher_login, ''), @pusher_login_prefilter)  AS pusher_login_hit,
    REGEXP_CONTAINS(message, r'^(Revert|Reapply) "')                      AS revert_hit
  FROM commits
  WHERE sha IS NOT NULL
    AND message IS NOT NULL
    AND repo IS NOT NULL
),

candidate_repos AS (
  SELECT DISTINCT repo
  FROM flagged
  WHERE message_hit OR author_email_hit OR author_name_hit OR pusher_login_hit
),

repo_totals AS (
  SELECT repo, COUNT(*) AS commits_in_repo_day
  FROM flagged
  GROUP BY repo
)

SELECT
  f.event_id,
  f.repo,
  f.pusher_login,
  f.pushed_at,
  f.push_size,
  f.sha,
  f.message,
  f.author_name,
  f.author_email,
  f.is_distinct,
  f.message_hit,
  f.author_email_hit,
  f.author_name_hit,
  f.pusher_login_hit,
  f.revert_hit,
  t.commits_in_repo_day
FROM flagged AS f
JOIN repo_totals AS t USING (repo)
LEFT JOIN candidate_repos AS cr USING (repo)
WHERE cr.repo IS NOT NULL OR f.revert_hit
ORDER BY f.pushed_at, f.event_id, f.sha
