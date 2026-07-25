"""
TechDebt Agent — CTO Skill 2 of 5.

Responsibility: Analyze git log output to detect technical debt signals.

Detects:
- Commit frequency and contributor activity
- Code churn: files changed repeatedly (hotspots)
- Bus factor: files touched by only 1 contributor
- Debt score: composite 0-10 metric
- Refactor priority recommendations

Input: git_log_text — output of:
  git log --stat --no-merges --since="90 days ago"
  or GitHub API commits payload (JSON)

done_when: state['tech_debt']['debt_score'] is a float.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import defaultdict
from typing import Any

from app.agents.cto.state import CTOState, CTORunConfig, CTOSkillResult

logger = logging.getLogger(__name__)

# Thresholds
HOTSPOT_MIN_CHANGES = 5        # file changed 5+ times in period = hotspot
BUS_FACTOR_MIN_COMMITS = 3     # file needs 3+ commits to evaluate bus factor
HIGH_CHURN_PCT = 0.30          # >30% of files are hotspots = high churn


def _parse_git_log(git_log: str) -> dict[str, Any]:
    """
    Parse `git log --stat` output.

    Returns:
        commits: list of {hash, author, date, files_changed}
        file_changes: {filename: {count, authors: set}}
    """
    commits = []
    file_changes: dict[str, dict] = defaultdict(lambda: {"count": 0, "authors": set()})

    current_commit: dict[str, Any] = {}
    current_author = ""

    for line in git_log.splitlines():
        line = line.strip()

        # Commit hash
        if re.match(r"^commit [0-9a-f]{7,40}$", line):
            if current_commit:
                commits.append(current_commit)
            current_commit = {"hash": line.split()[1][:8], "author": "", "date": "", "files": []}

        elif line.startswith("Author:"):
            current_author = line.replace("Author:", "").strip()
            # Extract just email or name
            match = re.search(r"<(.+?)>", current_author)
            current_author = match.group(1) if match else current_author.split()[0]
            if current_commit:
                current_commit["author"] = current_author

        elif line.startswith("Date:"):
            if current_commit:
                current_commit["date"] = line.replace("Date:", "").strip()[:10]

        # File change lines: "path/to/file.py | 12 +++--"
        elif "|" in line and ("++" in line or "--" in line or "Bin" in line):
            parts = line.split("|")
            if len(parts) >= 2:
                filename = parts[0].strip()
                if filename and not filename.startswith("{"):
                    if current_commit:
                        current_commit.setdefault("files", []).append(filename)
                    file_changes[filename]["count"] += 1
                    file_changes[filename]["authors"].add(current_author)

    if current_commit:
        commits.append(current_commit)

    return {"commits": commits, "file_changes": dict(file_changes)}


def _compute_debt_metrics(parsed: dict[str, Any]) -> dict[str, Any]:
    """Pure calculation."""
    commits = parsed["commits"]
    file_changes = parsed["file_changes"]

    if not commits:
        return {"debt_score": 0.0, "total_commits": 0}

    total_commits = len(commits)
    authors = {c["author"] for c in commits if c.get("author")}
    active_contributors = len(authors)

    # Hotspots: files changed >= HOTSPOT_MIN_CHANGES times
    hotspots = [
        {
            "file": fname,
            "changes": data["count"],
            "authors": len(data["authors"]),
            "bus_factor_risk": len(data["authors"]) == 1 and data["count"] >= BUS_FACTOR_MIN_COMMITS,
        }
        for fname, data in file_changes.items()
        if data["count"] >= HOTSPOT_MIN_CHANGES
    ]
    hotspots.sort(key=lambda x: x["changes"], reverse=True)

    total_files = len(file_changes)
    churn_rate = len(hotspots) / total_files if total_files else 0

    # Bus factor: files only one person ever touched
    bus_factor_files = [
        f for f, d in file_changes.items()
        if len(d["authors"]) == 1 and d["count"] >= BUS_FACTOR_MIN_COMMITS
    ]
    bus_factor_score = len(bus_factor_files) / total_files if total_files else 0

    # Debt score: 0-10 composite
    # Components: churn (0-4), bus_factor (0-3), commit_density (0-3)
    churn_component = min(4.0, churn_rate * 13.3)
    bus_component = min(3.0, bus_factor_score * 10)
    # Low commit count per contributor = low code sharing = higher debt
    commits_per_contributor = total_commits / max(active_contributors, 1)
    density_component = 3.0 if commits_per_contributor > 50 else commits_per_contributor / 50 * 3

    debt_score = round(churn_component + bus_component + density_component, 2)

    # Refactor priorities
    refactor_priorities = []
    for h in hotspots[:5]:
        severity = "critical" if h["changes"] > 20 else "high" if h["changes"] > 10 else "medium"
        refactor_priorities.append({
            "area": h["file"],
            "severity": severity,
            "changes_in_period": h["changes"],
            "estimated_days": max(1, h["changes"] // 5),
            "bus_factor_risk": h["bus_factor_risk"],
        })

    return {
        "total_commits": total_commits,
        "active_contributors": active_contributors,
        "total_files_changed": total_files,
        "churn_rate": round(churn_rate, 3),
        "hotspot_files": hotspots[:10],
        "bus_factor_files_count": len(bus_factor_files),
        "bus_factor_score": round(bus_factor_score, 3),
        "debt_score": debt_score,
        "refactor_priorities": refactor_priorities,
    }


async def _generate_debt_narrative(metrics: dict[str, Any], settings) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=0.2,
        max_tokens=512,
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or None,
    )

    top_hotspots = "\n".join(
        f"  - {h['file']} ({h['changes']} changes, {h['authors']} contributors)"
        for h in metrics.get("hotspot_files", [])[:5]
    ) or "  None detected"

    messages = [
        SystemMessage(content=(
            "Sen deneyimli bir CTO ve yazılım mimarısın. "
            "Git geçmişinden elde edilen teknik borç göstergelerini analiz et ve Türkçe olarak "
            "kısa, eyleme dönüştürülebilir bir özet yaz. "
            "Yanıt şu yapıda olsun:\n"
            "1. Teknik borç durumunun 1-2 cümlelik değerlendirmesi (skor ve churn odaklı)\n"
            "2. En riskli 1-2 alan (bus factor, hotspot)\n"
            "3. Ekibin sprint'e alması gereken 2-3 somut iyileştirme (öncelik sırasıyla)\n"
            "Geliştirici deneyimiyle ilgili pratik öneriler ekle."
        )),
        HumanMessage(content=(
            f"Teknik Borç Skoru: {metrics['debt_score']:.1f}/10\n"
            f"Toplam Commit (dönem): {metrics['total_commits']}\n"
            f"Aktif Katkıcı: {metrics['active_contributors']}\n"
            f"Kod Değişim Oranı (Churn): %{metrics['churn_rate']*100:.1f}\n"
            f"Bus Factor Riski Olan Dosya: {metrics['bus_factor_files_count']}\n\n"
            f"En Yoğun Değişen Dosyalar (Hotspot):\n{top_hotspots}"
        )),
    ]
    response = await llm.ainvoke(messages)
    return response.content.strip()


async def run_tech_debt_agent(
    state: CTOState,
    config: CTORunConfig,
) -> CTOSkillResult:
    """
    TechDebt Skill.
    done_when: state['tech_debt']['debt_score'] is a float.
    """
    git_log = state.get("git_log_text")
    if not git_log:
        return CTOSkillResult(
            ok=True,
            patch={"tech_debt": None},
            confidence=1.0,
            detail="No git log data provided — TechDebtAgent skipped.",
        )

    try:
        from app.config import get_settings
        settings = get_settings()

        parsed = _parse_git_log(git_log)
        metrics = _compute_debt_metrics(parsed)

        if metrics.get("total_commits", 0) == 0:
            return CTOSkillResult(
                ok=False,
                detail="Could not parse any commits from git log.",
                confidence=0.3,
                needs_review=True,
            )

        narrative = await _generate_debt_narrative(metrics, settings)
        metrics["narrative"] = narrative

        debt_score = metrics["debt_score"]
        needs_review = debt_score >= 7.0
        confidence = 0.90 if not needs_review else 0.80

        logger.info(
            "TechDebtAgent: job=%s commits=%d debt_score=%.1f hotspots=%d",
            state.get("job_id"),
            metrics["total_commits"],
            debt_score,
            len(metrics.get("hotspot_files", [])),
        )

        return CTOSkillResult(
            ok=True,
            patch={"tech_debt": metrics},
            confidence=confidence,
            needs_review=needs_review,
            detail=(
                f"Tech debt score: {debt_score:.1f}/10, "
                f"churn: {metrics['churn_rate']*100:.1f}%, "
                f"hotspots: {len(metrics.get('hotspot_files', []))}"
            ),
        )

    except Exception as exc:
        logger.exception("TechDebtAgent failed for job=%s", state.get("job_id"))
        return CTOSkillResult(ok=False, detail=f"TechDebtAgent error: {exc}")
