"""Render the registry as `docs/kvkk/veri-envanteri-uretilen.md` (generated; a test fails when it is stale).

Regenerate with `python -m app.services.privacy.inventory_doc` from `backend/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.database import Base
from app.services import org_erasure
from app.services.privacy.registry import THIRD_PARTIES, Flow
from app.services.privacy.registry_stores import STORES
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


def render() -> str:
    out = [HEADER, "## Tables\n",
           f"{len(TABLES)} tables hold or may hold personal data ({len(Base.metadata.tables)} tables exist).\n",
           "| Table | Whose | Purpose | Columns (category) | Retention class | On organisation erasure | Third parties |",
           "|---|---|---|---|---|---|---|"]
    for name in sorted(TABLES):
        t = TABLES[name]
        cols = ", ".join(f"`{c}` ({cat.value})" for c, cat in sorted(t.columns.items())) or "-"
        out.append(f"| `{name}` | {t.subject.value} | {t.purpose} | {cols} | {t.retention.value} | "
                   f"{_erasure(name)} | {_flows(t.flows)} |")
    out += ["", "## Stores outside the tables\n",
            "| Store | Holds | Where | Retention class | Lifetime | Erased by |", "|---|---|---|---|---|---|"]
    for s in STORES:
        out.append(f"| `{s.key}` | {s.holds} | {s.where} | {s.retention.value} | {s.ttl} | {s.erased_by} |")
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
