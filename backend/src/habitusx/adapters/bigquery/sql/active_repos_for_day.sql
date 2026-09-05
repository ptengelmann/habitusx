-- active_repos_for_day
--
-- Every repository that received at least one push on one UTC day. Used to draw the
-- control cohort of the panel. Reads only the type and repo.name columns, so it stays
-- cheap, and it works after the October 2025 payload change because repo.name is an
-- event field, not part of the payload.

SELECT DISTINCT repo.name AS repo
FROM `{{ table }}`
WHERE type = 'PushEvent'
  AND repo.name IS NOT NULL
