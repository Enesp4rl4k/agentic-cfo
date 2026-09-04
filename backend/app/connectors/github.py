"""GitHub connector — engineering signals for the CTO view.

Adapter over `app.services.github_connector.GitHubConnector` (the raw REST
client). Emits one `CanonicalRow` per commit / pull request / issue, keyed by a
stable `source_record_id` so re-syncs upsert instead of duplicating.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.connectors.base import (
    CanonicalRow,
    Connector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorPayload,
    Watermark,
)
from app.connectors.registry import register

# When a connection has never synced, look back this far on the first pull.
_FIRST_SYNC_LOOKBACK_DAYS = 30
# Hard cap so a stale connection can't request a giant backfill.
_MAX_LOOKBACK_DAYS = 180


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@register
class GitHubConnector(Connector):
    name: ClassVar[str] = "github"
    domain: ClassVar[str] = "engineering"
    kernel_role: ClassVar[str | None] = "cto"

    def _client(self, secret: Mapping[str, Any]) -> Any:
        token = (secret or {}).get("token")
        if not token:
            raise ConnectorAuthError("github: missing personal access token")
        from app.services.github_connector import GitHubConnector as _ApiClient

        return _ApiClient(token=token)

    @staticmethod
    def _owner_repo(config: Mapping[str, Any]) -> tuple[str, str]:
        owner = (config or {}).get("owner")
        repo = (config or {}).get("repo")
        if not owner or not repo:
            raise ConnectorConfigError("github: config needs 'owner' and 'repo'")
        return str(owner), str(repo)

    async def health(
        self, *, config: Mapping[str, Any], secret: Mapping[str, Any]
    ) -> ConnectorHealth:
        # `_client` raises ConnectorAuthError on a missing token. Building it
        # outside the try let that escape health(), which by contract returns a
        # verdict rather than raising — the API turned it into a 500.
        try:
            client = self._client(secret)
            user = await client.validate_token()
        except Exception as exc:
            return ConnectorHealth(ok=False, detail=f"token check failed: {exc}")
        owner, repo = self._owner_repo(config)
        return ConnectorHealth(
            ok=True,
            detail=f"authenticated as {user.get('login', '?')}",
            account=f"{owner}/{repo}",
        )

    async def fetch(
        self,
        *,
        org_id: str,
        config: Mapping[str, Any],
        secret: Mapping[str, Any],
        since: Watermark,
    ) -> ConnectorPayload:
        client = self._client(secret)
        owner, repo = self._owner_repo(config)

        now = datetime.now(UTC)
        since_dt = since.since
        if since_dt is not None and since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=UTC)
        if since_dt is not None:
            lookback_days = max(1, min(_MAX_LOOKBACK_DAYS, (now - since_dt).days + 1))
        else:
            lookback_days = int((config or {}).get("days", _FIRST_SYNC_LOOKBACK_DAYS))
        lookback_days = max(1, min(_MAX_LOOKBACK_DAYS, lookback_days))

        data = await client.fetch(owner=owner, repo=repo, days=lookback_days)
        if data.error:
            raise ConnectorAuthError(f"github fetch failed: {data.error}")

        rows: list[CanonicalRow] = []

        for c in data.commits:
            occurred = _iso_to_dt(c.date) or now
            rows.append(
                CanonicalRow(
                    source_record_id=f"commit:{c.sha}",
                    signal_type="commit",
                    occurred_at=occurred,
                    actor=c.author,
                    title=c.message[:280],
                    magnitude=int((c.additions or 0) + (c.deletions or 0)),
                    attributes={
                        "sha": c.sha,
                        "files_changed": c.files_changed,
                        "additions": c.additions,
                        "deletions": c.deletions,
                    },
                )
            )

        for pr in data.pull_requests:
            created = _iso_to_dt(pr.created_at)
            merged = _iso_to_dt(pr.merged_at)
            cycle_h = (
                int((merged - created).total_seconds() // 3600)
                if created and merged
                else None
            )
            rows.append(
                CanonicalRow(
                    source_record_id=f"pr:{pr.number}",
                    signal_type="pull_request",
                    occurred_at=merged or created or now,
                    actor=pr.author,
                    title=pr.title[:280],
                    magnitude=cycle_h,
                    attributes={
                        "number": pr.number,
                        "state": pr.state,
                        "review_count": pr.review_count,
                        "comments": pr.comments,
                        "additions": pr.additions,
                        "deletions": pr.deletions,
                        "files_changed": pr.files_changed,
                        "merged": merged is not None,
                    },
                )
            )

        incident_labels = {"bug", "incident", "hotfix", "critical", "production"}
        for issue in data.issues:
            labels_lc = [str(lbl).lower() for lbl in (issue.labels or [])]
            is_incident = any(lbl in incident_labels for lbl in labels_lc)
            rows.append(
                CanonicalRow(
                    source_record_id=f"issue:{issue.number}",
                    signal_type="incident" if is_incident else "issue",
                    occurred_at=_iso_to_dt(issue.created_at) or now,
                    actor=None,
                    title=issue.title[:280],
                    magnitude=int(issue.comments or 0),
                    attributes={
                        "number": issue.number,
                        "state": issue.state,
                        "labels": issue.labels,
                        "closed_at": issue.closed_at,
                    },
                )
            )

        return ConnectorPayload(
            rows=rows,
            next_watermark=Watermark(since=now),
            warnings=[] if rows else ["github: no activity in the lookback window"],
        )
