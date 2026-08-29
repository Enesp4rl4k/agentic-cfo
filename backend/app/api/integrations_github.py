"""
GitHub Connector API — /api/v1/integrations/github/*

POST /integrations/github/connect      → Save PAT token + validate (DB-persisted)
GET  /integrations/github/status       → Check if connected, show repo info
POST /integrations/github/sync         → Fetch latest data + run CTO analysis
DELETE /integrations/github/disconnect → Remove stored token

Token persistence
-----------------
Tokens are stored in the erp_integrations table (provider='github').
The source_config JSON field holds: {token, owner, repo, days, github_login,
last_sync, last_commit_count, last_pr_count}.

SECURITY NOTE: In production, encrypt the token field using Fernet
(see app.services.field_encryption) before storing.
The current implementation stores tokens as plaintext because
field_encryption_enabled defaults to False. Set it to True in production.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)

# ── DB helpers ────────────────────────────────────────────────────────────────

async def _load_github_config(org_id: str, db: AsyncSession) -> dict[str, Any] | None:
    """Load GitHub config from erp_integrations table."""
    try:
        from app.models.erp_integration import ERPIntegration
        result = await db.execute(
            select(ERPIntegration).where(
                ERPIntegration.org_id   == org_id,
                ERPIntegration.provider == "github",
                ERPIntegration.status   == "active",
            )
        )
        row = result.scalar_one_or_none()
        if row and row.source_config:
            return json.loads(row.source_config) if isinstance(row.source_config, str) else row.source_config
    except Exception as exc:
        logger.warning("GitHub config load failed: %s", exc)
    return None


async def _save_github_config(
    org_id: str,
    config: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Upsert GitHub config into erp_integrations table."""
    try:
        from app.models.erp_integration import ERPIntegration
        now = datetime.now(UTC)

        result = await db.execute(
            select(ERPIntegration).where(
                ERPIntegration.org_id   == org_id,
                ERPIntegration.provider == "github",
            )
        )
        row = result.scalar_one_or_none()

        config_json = json.dumps(config)

        if row:
            row.source_config = config_json
            row.status        = "active"
            row.updated_at    = now
        else:
            row = ERPIntegration(
                org_id        = org_id,
                provider      = "github",
                display_name  = f"GitHub ({config.get('owner', '')}/{config.get('repo', '')})",
                source_config = config_json,
                status        = "active",
                connected_at  = now,
            )
            db.add(row)

        await db.commit()
    except Exception as exc:
        logger.warning("GitHub config save failed: %s", exc)


async def _delete_github_config(org_id: str, db: AsyncSession) -> None:
    """Remove GitHub integration from DB."""
    try:
        from app.models.erp_integration import ERPIntegration
        await db.execute(
            delete(ERPIntegration).where(
                ERPIntegration.org_id   == org_id,
                ERPIntegration.provider == "github",
            )
        )
        await db.commit()
    except Exception as exc:
        logger.warning("GitHub config delete failed: %s", exc)


def _require_org(user: User) -> str:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="Organizasyona üye değilsiniz.")
    return str(user.org_id)


# ── Schemas ───────────────────────────────────────────────────────────────────

class GitHubConnectRequest(BaseModel):
    token: str          # GitHub Personal Access Token (ghp_...)
    owner: str          # GitHub org or user name
    repo: str           # Repository name
    days: int = 30      # How many days of history to fetch


class GitHubSyncRequest(BaseModel):
    days: int = 30      # Days of history to include in CTO analysis


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/integrations/github/connect")
async def connect_github(
    body: GitHubConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Validate a GitHub PAT token and save the connector config.
    Returns the authenticated GitHub user info.
    """
    org_id = _require_org(user)

    from app.services.github_connector import GitHubConnector
    connector = GitHubConnector(token=body.token)

    try:
        github_user = await connector.validate_token()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub token geçersiz veya yetki yetersiz: {exc}",
        )

    # Persist config to DB (replaces in-memory store)
    config = {
        "token":        body.token,
        "owner":        body.owner,
        "repo":         body.repo,
        "days":         body.days,
        "github_login": github_user.get("login"),
        "connected":    True,
    }
    await _save_github_config(org_id, config, db)

    logger.info("GitHub connected for org=%s repo=%s/%s", org_id, body.owner, body.repo)

    return {
        "data": {
            "connected": True,
            "github_login": github_user["login"],
            "repo": f"{body.owner}/{body.repo}",
            "message": f"GitHub bağlantısı başarılı — {github_user['login']} olarak giriş yapıldı.",
        },
        "error": None,
    }


@router.get("/integrations/github/status")
async def github_status(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return current GitHub connector status for this org (DB-backed)."""
    org_id = _require_org(user)
    config = await _load_github_config(org_id, db)

    if not config:
        return {
            "data": {
                "connected":    False,
                "repo":         None,
                "github_login": None,
                "last_sync":    None,
            },
            "error": None,
        }

    return {
        "data": {
            "connected":         True,
            "repo":              f"{config.get('owner', '')}/{config.get('repo', '')}",
            "owner":             config.get("owner"),
            "github_login":      config.get("github_login"),
            "last_sync":         config.get("last_sync"),
            "last_commit_count": config.get("last_commit_count"),
            "last_pr_count":     config.get("last_pr_count"),
        },
        "error": None,
    }


@router.post("/integrations/github/sync")
async def sync_github(
    body: GitHubSyncRequest,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Fetch latest GitHub data and run CTO analysis pipeline.
    Config is loaded from DB — survives server restarts.
    """
    org_id = _require_org(user)
    config = await _load_github_config(org_id, db)

    if not config:
        raise HTTPException(
            status_code=400,
            detail="GitHub bağlantısı bulunamadı. Önce /integrations/github/connect ile bağlanın.",
        )

    import uuid

    from app.agents.cto.orchestrator import run_cto_pipeline
    from app.services.github_connector import GitHubConnector

    connector = GitHubConnector(token=config["token"])

    # Fetch GitHub data
    try:
        github_data = await connector.fetch(
            owner=config["owner"],
            repo=config["repo"],
            days=body.days,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub veri çekme başarısız: {exc}",
        )

    if github_data.error:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API hatası: {github_data.error}",
        )

    # Convert to CSV inputs for CTO pipeline
    git_log_csv  = github_data.to_git_log_csv()
    incident_csv = github_data.to_incident_csv()
    sprint_csv   = github_data.to_sprint_csv()

    # Run CTO analysis with fetched data
    job_id = str(uuid.uuid4())
    try:
        result = await run_cto_pipeline(
            job_id=job_id,
            company_name=config.get("company_name"),
            git_log_text=git_log_csv,
            incident_csv=incident_csv or None,
            sprint_csv=sprint_csv or None,
        )
    except Exception as exc:
        logger.error("CTO pipeline failed after GitHub sync: %s", exc)
        result = {"error": str(exc)}

    # Persist last sync info back to DB
    config.update({
        "last_sync":         datetime.now(UTC).isoformat(),
        "last_commit_count": len(github_data.commits),
        "last_pr_count":     len(github_data.pull_requests),
    })
    await _save_github_config(org_id, config, db)

    return {
        "data": {
            "job_id":         job_id,
            "github_summary": github_data.summary(),
            "cto_result":     result,
        },
        "error": result.get("error") if isinstance(result, dict) else None,
    }


@router.delete("/integrations/github/disconnect")
async def disconnect_github(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Remove GitHub connector for this org (DB-backed)."""
    org_id = _require_org(user)
    await _delete_github_config(org_id, db)
    logger.info("GitHub disconnected for org=%s", org_id)
    return {"data": {"connected": False}, "error": None}
