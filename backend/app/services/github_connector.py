"""
GitHub Connector Service — Personal Access Token (PAT) based.

Fetches repository activity data from GitHub API and converts it
to the CSV format expected by the CTO agent pipeline.

Data collected:
  - Recent commits (git log equivalent)
  - Open pull requests
  - Recent issues / incidents
  - Repository statistics

Usage:
    connector = GitHubConnector(token="ghp_...")
    data = await connector.fetch(owner="myorg", repo="myrepo", days=30)
    git_log_csv = data.to_git_log_csv()
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Max items fetched per resource (avoid rate limit exhaustion)
MAX_COMMITS  = 100
MAX_PRS      = 50
MAX_ISSUES   = 50


@dataclass
class CommitRecord:
    sha: str
    message: str
    author: str
    date: str
    files_changed: int
    additions: int
    deletions: int


@dataclass
class PRRecord:
    number: int
    title: str
    author: str
    state: str
    created_at: str
    merged_at: str | None
    review_count: int
    comments: int
    additions: int
    deletions: int
    files_changed: int


@dataclass
class IssueRecord:
    number: int
    title: str
    state: str
    labels: list[str]
    created_at: str
    closed_at: str | None
    comments: int


@dataclass
class GitHubData:
    owner: str
    repo: str
    default_branch: str
    stars: int
    forks: int
    open_issues: int
    commits: list[CommitRecord] = field(default_factory=list)
    pull_requests: list[PRRecord] = field(default_factory=list)
    issues: list[IssueRecord] = field(default_factory=list)
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    error: str | None = None

    def to_git_log_csv(self) -> str:
        """Convert commits to the format expected by CTO git_log_text input."""
        if not self.commits:
            return ""
        lines = ["date,author,sha,message,files_changed,additions,deletions"]
        for c in self.commits:
            msg = c.message.replace(",", ";").replace("\n", " ")[:120]
            lines.append(
                f"{c.date},{c.author},{c.sha[:8]},{msg},"
                f"{c.files_changed},{c.additions},{c.deletions}"
            )
        return "\n".join(lines)

    def to_incident_csv(self) -> str:
        """Convert open issues labeled as bugs/incidents to incident CSV."""
        incident_labels = {"bug", "incident", "hotfix", "critical", "production"}
        incidents = [
            i for i in self.issues
            if any(lbl.lower() in incident_labels for lbl in i.labels)
        ]
        if not incidents:
            return ""
        lines = ["id,title,state,created_at,closed_at,severity,comments"]
        for i in incidents:
            title = i.title.replace(",", ";")[:100]
            severity = "critical" if "critical" in [l.lower() for l in i.labels] else "medium"
            lines.append(
                f"GH-{i.number},{title},{i.state},"
                f"{i.created_at},{i.closed_at or ''},"
                f"{severity},{i.comments}"
            )
        return "\n".join(lines)

    def to_sprint_csv(self) -> str:
        """Convert PR activity to a pseudo-sprint CSV."""
        if not self.pull_requests:
            return ""
        lines = ["pr_number,title,author,state,created_at,merged_at,review_count,cycle_time_days"]
        for pr in self.pull_requests:
            title = pr.title.replace(",", ";")[:80]
            cycle_time = ""
            if pr.merged_at and pr.created_at:
                try:
                    created = datetime.fromisoformat(pr.created_at.replace("Z", "+00:00"))
                    merged  = datetime.fromisoformat(pr.merged_at.replace("Z", "+00:00"))
                    cycle_time = str(round((merged - created).total_seconds() / 86400, 1))
                except Exception:
                    pass
            lines.append(
                f"{pr.number},{title},{pr.author},{pr.state},"
                f"{pr.created_at},{pr.merged_at or ''},"
                f"{pr.review_count},{cycle_time}"
            )
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        return {
            "repo": f"{self.owner}/{self.repo}",
            "branch": self.default_branch,
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "commits_fetched": len(self.commits),
            "prs_fetched": len(self.pull_requests),
            "issues_fetched": len(self.issues),
            "fetched_at": self.fetched_at,
        }


class GitHubConnector:
    """
    Async GitHub REST API v3 client using Personal Access Token.

    Token needs scopes: repo (or public_repo for public repos)
    """

    BASE = "https://api.github.com"

    def __init__(self, token: str) -> None:
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make a single GET request. Returns parsed JSON or raises."""
        import httpx
        url = f"{self.BASE}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._headers, params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def validate_token(self) -> dict[str, str]:
        """Check if the token is valid. Returns user info dict."""
        data = await self._get("/user")
        return {"login": data["login"], "name": data.get("name", ""), "type": data.get("type", "")}

    async def fetch(
        self,
        owner: str,
        repo: str,
        days: int = 30,
    ) -> GitHubData:
        """
        Fetch commits, PRs, and issues for the past `days` days.
        Returns a GitHubData object with CSV conversion helpers.
        """
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        try:
            # Repo metadata
            repo_data = await self._get(f"/repos/{owner}/{repo}")
            github_data = GitHubData(
                owner=owner,
                repo=repo,
                default_branch=repo_data.get("default_branch", "main"),
                stars=repo_data.get("stargazers_count", 0),
                forks=repo_data.get("forks_count", 0),
                open_issues=repo_data.get("open_issues_count", 0),
            )

            # Fetch in parallel
            commits_task  = self._fetch_commits(owner, repo, since)
            prs_task      = self._fetch_prs(owner, repo, since)
            issues_task   = self._fetch_issues(owner, repo, since)

            commits, prs, issues = await asyncio.gather(
                commits_task, prs_task, issues_task,
                return_exceptions=True,
            )

            if isinstance(commits, list):
                github_data.commits = commits
            else:
                logger.warning("GitHub commits fetch failed: %s", commits)

            if isinstance(prs, list):
                github_data.pull_requests = prs
            else:
                logger.warning("GitHub PRs fetch failed: %s", prs)

            if isinstance(issues, list):
                github_data.issues = issues
            else:
                logger.warning("GitHub issues fetch failed: %s", issues)

            return github_data

        except Exception as exc:
            logger.error("GitHub fetch failed for %s/%s: %s", owner, repo, exc)
            return GitHubData(
                owner=owner, repo=repo,
                default_branch="main", stars=0, forks=0, open_issues=0,
                error=str(exc),
            )

    async def _fetch_commits(self, owner: str, repo: str, since: str) -> list[CommitRecord]:
        data = await self._get(
            f"/repos/{owner}/{repo}/commits",
            {"since": since, "per_page": MAX_COMMITS},
        )
        records = []
        for item in data:
            commit = item.get("commit", {})
            stats  = item.get("stats", {})
            records.append(CommitRecord(
                sha=item.get("sha", ""),
                message=commit.get("message", "").split("\n")[0],
                author=commit.get("author", {}).get("name", "unknown"),
                date=commit.get("author", {}).get("date", ""),
                files_changed=len(item.get("files", [])),
                additions=stats.get("additions", 0),
                deletions=stats.get("deletions", 0),
            ))
        return records

    async def _fetch_prs(self, owner: str, repo: str, since: str) -> list[PRRecord]:
        data = await self._get(
            f"/repos/{owner}/{repo}/pulls",
            {"state": "all", "sort": "updated", "direction": "desc", "per_page": MAX_PRS},
        )
        # Filter by since date
        cutoff = datetime.fromisoformat(since)
        records = []
        for pr in data:
            updated = pr.get("updated_at", "")
            try:
                if datetime.fromisoformat(updated.replace("Z", "+00:00")) < cutoff:
                    continue
            except Exception:
                pass

            records.append(PRRecord(
                number=pr["number"],
                title=pr.get("title", ""),
                author=pr.get("user", {}).get("login", "unknown"),
                state=pr.get("state", ""),
                created_at=pr.get("created_at", ""),
                merged_at=pr.get("merged_at"),
                review_count=pr.get("review_comments", 0),
                comments=pr.get("comments", 0),
                additions=pr.get("additions", 0),
                deletions=pr.get("deletions", 0),
                files_changed=pr.get("changed_files", 0),
            ))
        return records

    async def _fetch_issues(self, owner: str, repo: str, since: str) -> list[IssueRecord]:
        data = await self._get(
            f"/repos/{owner}/{repo}/issues",
            {"state": "all", "since": since, "per_page": MAX_ISSUES},
        )
        records = []
        for issue in data:
            # Skip pull requests (GitHub issues API includes PRs)
            if "pull_request" in issue:
                continue
            records.append(IssueRecord(
                number=issue["number"],
                title=issue.get("title", ""),
                state=issue.get("state", ""),
                labels=[lbl.get("name", "") for lbl in issue.get("labels", [])],
                created_at=issue.get("created_at", ""),
                closed_at=issue.get("closed_at"),
                comments=issue.get("comments", 0),
            ))
        return records
