"""Shared retention settings used by both the fetcher and the cleanup task.

Keep the fetcher's ingest window and the cleanup cutoff in sync — otherwise
articles in the "accepted by fetcher but already expired" range get inserted
and deleted on every poll, inflating new-article counts and DB churn.
"""

ARTICLE_RETENTION_DAYS = 14
