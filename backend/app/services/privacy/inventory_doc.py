"""Render the registry as `docs/kvkk/veri-envanteri-uretilen.md` (generated; a test fails when it is stale).

Regenerate with `python -m app.services.privacy.inventory_doc` from `backend/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.database import Base
from app.services import org_erasure
from app.services.privacy.registry import THIRD_PARTIES, Flow
from app.services.privacy.registry_stores import PURGES, STORES
from app.services.privacy.registry_tables import TABLES

DOC_PATH = Path(__file__).resolve().parents[4] / "docs" / "kvkk" / "veri-envanteri-uretilen.md"
HEADER = """# Kisisel veri haritasi (uretilmis)

> GENERATED from `backend/app/services/privacy/registry*.py` by `python -m app.services.privacy.inventory_doc`.
> Do not edit by hand: `tests/test_privacy_registry.py` fails when this file is stale. It records what the CODE
> does. Legal bases, retention periods and the cross-border position are not decided here:
> see [avukata-sorular.md](avukata-sorular.md). PR #68's `veri-envanteri.md` is the hand-written, line-referenced
> companion; [mismatches](veri-envanteri-farklar.md) lists where the two disagree.
"""


def _erasure(table: str) -> str:
    if table in org_erasure.BOOKKEEPING_TABLES:
        return "kept (proof, no personal data)"
    if table in org_erasure.RETAINED:
        return "kept, columns scrubbed"
    return "deleted"


def _flows(flows: tuple[Flow, ...]) -> str:
    return ", ".join(f.value for f in flows) or "-"


def _retention_job(table: str) -> str:
    """Which retention purges touch this table and whether each is in effect; `-` when none does."""
    keys = [f"`{k}` ({p.enforcement.value})" for k, p in PURGES.items() if table in p.tables]
    return ", ".join(keys) or "- (no retention job: kept until erasure)"


ENFORCEMENT_NOTE = """## Retention: in effect or not

`enforced`: the retention job deletes it whatever `RETENTION_DRY_RUN` says (nothing reads it, or it is erasure rather
than retention). `dry_run_default`: counted only while `RETENTION_DRY_RUN=true`, the default; deleted once the operator
sets it to false after reviewing the first report (docs/ops/first-deploy-checklist.md). Until then that period is NOT
in effect. `not_applicable`: no retention job (kept until erasure, a cache time-to-live, or outside our reach).
The job reads this table (`retention.ENFORCED_ALWAYS`); `tests/test_privacy_registry.py` ties both to the code.
"""


def render() -> str:
    out = [HEADER, "## Tables\n",
           f"{len(TABLES)} tables hold or may hold personal data ({len(Base.metadata.tables)} tables exist).\n",
           "| Table | Whose | Purpose | Columns (category) | Retention class | Retention job | On organisation erasure "
           "| Third parties |",
           "|---|---|---|---|---|---|---|---|"]
    for name in sorted(TABLES):
        t = TABLES[name]
        cols = ", ".join(f"`{c}` ({cat.value})" for c, cat in sorted(t.columns.items())) or "-"
        out.append(f"| `{name}` | {t.subject.value} | {t.purpose} | {cols} | {t.retention.value} | "
                   f"{_retention_job(name)} | {_erasure(name)} | {_flows(t.flows)} |")
    out += ["", "## Stores outside the tables\n",
            "| Store | Holds | Where | Retention class | Lifetime | In effect | Erased by |", "|---|---|---|---|---|---|---|"]
    for s in STORES:
        effect = f"{s.enforcement.value if s.enforcement else '?'}: {s.enforcement_why}"
        out.append(f"| `{s.key}` | {s.holds} | {s.where} | {s.retention.value} | {s.ttl} | {effect} | {s.erased_by} |")
    out += ["", ENFORCEMENT_NOTE, "| Purge | What | Tables | Period | In effect | Why |", "|---|---|---|---|---|---|"]
    for key, p in PURGES.items():
        tables = ", ".join(f"`{t}`" for t in p.tables)
        out.append(f"| `{key}` | {p.what} | {tables} | {p.period} | {p.enforcement.value} | {p.why} |")
    out += ["", "## Third parties\n"]
    for flow, tp in THIRD_PARTIES.items():
        users = sorted([n for n, t in TABLES.items() if flow in t.flows] + [s.key for s in STORES if flow in s.flows])
        out += [f"### {tp.name}\n", f"- Receives: {tp.sends}.",
                f"- Masked before sending: {'yes' if tp.masked else 'NO'}.",
                f"- Code: {tp.where}.", f"- Off / on: {tp.switch}.", f"- Open question: {tp.question}",
                f"- Registry entries that can reach it: {', '.join(f'`{u}`' for u in users) or '-'}.", ""]
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":  # pragma: no cover
    import app.models  # noqa: F401

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(render(), encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {DOC_PATH}\n")
