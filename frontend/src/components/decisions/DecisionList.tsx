"use client";

import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/hooks/useI18n";
import type { DecisionEntry } from "@/lib/api/decisionRecords";

/** member user id -> display name, when the caller may read the member list. */
export type MemberNames = Record<string, string>;

function shown(key: string, value: unknown): string {
  if (value === null || value === undefined) return "–";
  if ((key.endsWith("_cents") || key.endsWith("_kurus")) && typeof value === "number") {
    return (value / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Snapshot({ label, data }: { label: string; data: Record<string, unknown> | null }) {
  if (!data) return null;
  return (
    <div>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="m-0 text-sm">
        {Object.entries(data).map(([k, v]) => (
          <span key={k} className="mr-3 inline-block">
            <span className="text-muted-foreground">{k}: </span>
            {shown(k, v)}
          </span>
        ))}
      </dd>
    </div>
  );
}

/** One row per decision: when, who (or which rule), what kind, what outcome, and the basis on demand. */
export function DecisionList({
  entries,
  names = {},
  onOpenHistory,
}: {
  entries: DecisionEntry[];
  names?: MemberNames;
  onOpenHistory?: (entry: DecisionEntry) => void;
}) {
  const { t } = useI18n();
  const d = t.decisionLog;
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {entries.map((e) => {
        const who =
          e.decided_via === "rule"
            ? `${d.viaRule}: ${e.rule_id ?? ""}`
            : e.decided_via === "system"
              ? d.viaSystem
              : (e.decided_by && names[e.decided_by]) || d.unknownPerson;
        return (
          <li key={e.id} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <time dateTime={e.decided_at} className="text-muted-foreground">
                {new Date(e.decided_at).toLocaleString()}
              </time>
              <span className="font-medium">{d.kinds[e.kind] ?? e.kind}</span>
              <Badge variant="outline">{d.outcomes[e.outcome] ?? e.outcome}</Badge>
              <span className="text-muted-foreground">{who}</span>
              {onOpenHistory && (
                <button type="button" className="ml-auto text-xs underline" onClick={() => onOpenHistory(e)}>
                  {d.historyOpen}
                </button>
              )}
            </div>
            {e.decided_via === "rule" && e.rule_id && (
              <p className="m-0 mt-1 text-xs text-muted-foreground">{d.ruleNote.replace("{id}", e.rule_id)}</p>
            )}
            {e.supersedes_id && <p className="m-0 mt-1 text-xs text-muted-foreground">{d.replaces}</p>}
            {e.superseded_by_id && <p className="m-0 mt-1 text-xs text-muted-foreground">{d.replacedBy}</p>}
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground">{d.detail}</summary>
              <dl className="m-0 mt-1 flex flex-col gap-1">
                {e.reason && (
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{d.reason}</dt>
                    <dd className="m-0 text-sm">{e.reason}</dd>
                  </div>
                )}
                <Snapshot label={d.before} data={e.before} />
                <Snapshot label={d.after} data={e.after} />
                {e.evidence_refs.length > 0 && (
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{d.evidence}</dt>
                    <dd className="m-0 text-sm">{e.evidence_refs.map((r) => `${r.type} ${r.id.slice(0, 8)}`).join(", ")}</dd>
                  </div>
                )}
              </dl>
            </details>
          </li>
        );
      })}
    </ul>
  );
}
