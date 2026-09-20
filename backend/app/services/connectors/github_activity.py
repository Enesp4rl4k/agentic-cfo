"""GitHub activity → CTO semantic overlay (commits/PRs/issues)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def overlay_from_github_data(data: Any) -> dict[str, Any]:
    """Pure mapping from GitHubData → last_cto_result fragment."""
    commits = list(getattr(data, "commits", None) or [])
    prs = list(
        getattr(data, "pull_requests", None)
        or getattr(data, "pull_requests", None)
        or []
    )
    list(getattr(data, "issues", None) or [])
    commit_n = len(commits)
    pr_n = len(prs)
    issue_n = int(getattr(data, "open_issues", 0) or 0)
    if commit_n >= 40:
        trend = "up"
    elif commit_n < 10:
        trend = "down"
    else:
        trend = "flat"
    health = max(0, min(100, 55 + min(commit_n, 30) - min(issue_n, 25)))
    return {
        "cto_summary": {
            "overall_health_score": health,
            "velocity_trend": trend,
        },
        "velocity": {"velocity_trend": trend, "commits": commit_n, "pull_requests": pr_n},
        "github_activity": {
            "repo": f"{getattr(data, 'owner', '')}/{getattr(data, 'repo', '')}",
            "commit_count": commit_n,
            "pr_count": pr_n,
            "open_issues": issue_n,
            "source": "github",
        },
    }


async def pull_github_cto_overlay(cfg: dict[str, Any]) -> dict[str, Any]:
    """Fetch GitHub activity when token+repo are configured. Empty dict if skipped."""
    token = str(cfg.get("github_token") or cfg.get("token") or "")
    owner = str(cfg.get("owner") or "")
    repo = str(cfg.get("repo") or "")
    days = int(cfg.get("days") or 30)
    if not token or not owner or not repo:
        logger.debug("GitHub overlay skipped: missing token/owner/repo")
        return {}
    try:
        from app.services.github_connector import GitHubConnector

        connector = GitHubConnector(token)
        data = await connector.fetch(owner=owner, repo=repo, days=days)
        if getattr(data, "error", None):
            logger.warning("GitHub overlay fetch error: %s", data.error)
            return {}
        return overlay_from_github_data(data)
    except Exception as exc:
        logger.warning("GitHub overlay failed: %s", exc)
        return {}
