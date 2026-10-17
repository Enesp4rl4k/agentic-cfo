/**
 * Runtime contract between what the audit pipeline returns on the wire and
 * the dashboard view. The page used to cast with a bare `any` for
 * findings/controls/coverage, so a renamed backend key surfaced as
 * `undefined` (the bug class the CHRO page hit on 2026-10-14). The single
 * entry point (POST /audit/analyze) normalizes exactly once; the summary
 * without its score is null and the view renders "—".
 */

import { isRecord, num, strOrNull, records } from "@/lib/wire";

export interface AuditFinding {
  finding_id: string;
  title: string;
  severity: string;
  status: string;
  due_date: string;
  owner: string;
  category: string;
  remediation_status: string;
  days_overdue: number | null;
}

export interface AuditSummaryView {
  overall_audit_score: number;
  audit_maturity: string;
  component_scores: Record<string, number>;
  top_risks: Array<{ domain: string; severity: string; message: string }>;
  quick_wins: Array<{ action: string; estimated_impact: string; effort: string }>;
  narrative: string;
}

export interface AuditResultView {
  job_id: string;
  findings: { top_overdue: AuditFinding[] } | null;
  controls: Record<string, unknown> | null;
  coverage: Record<string, unknown> | null;
  audit_summary: AuditSummaryView | null;
  error: string | null;
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function numScores(v: unknown): Record<string, number> {
  if (!isRecord(v)) return {};
  const out: Record<string, number> = {};
  for (const [k, value] of Object.entries(v)) {
    const n = num(value);
    if (n !== null) out[k] = n;
  }
  return out;
}

function normalizeFinding(raw: Record<string, unknown>): AuditFinding | null {
  const title = str(raw.title);
  if (title === "") return null;
  return {
    finding_id: str(raw.finding_id),
    title,
    severity: str(raw.severity),
    status: str(raw.status),
    due_date: str(raw.due_date),
    owner: str(raw.owner),
    category: str(raw.category),
    remediation_status: str(raw.remediation_status),
    days_overdue: num(raw.days_overdue),
  };
}

function normalizeSummary(raw: unknown): AuditSummaryView | null {
  if (!isRecord(raw)) return null;
  const score = num(raw.overall_audit_score);
  if (score === null) return null;
  return {
    overall_audit_score: score,
    audit_maturity: str(raw.audit_maturity),
    component_scores: numScores(raw.component_scores),
    top_risks: records(raw.top_risks)
      .map((r) => ({
        domain: str(r.domain),
        severity: str(r.severity),
        message: str(r.message),
      }))
      .filter((r) => r.message !== ""),
    quick_wins: records(raw.quick_wins)
      .map((w) => ({
        action: str(w.action),
        estimated_impact: str(w.estimated_impact),
        effort: str(w.effort),
      }))
      .filter((w) => w.action !== ""),
    narrative: str(raw.narrative),
  };
}

export function normalizeAuditResult(raw: unknown): AuditResultView | null {
  if (!isRecord(raw)) return null;

  const findings = isRecord(raw.findings)
    ? {
        top_overdue: records(raw.findings.top_overdue)
          .map(normalizeFinding)
          .filter((f): f is AuditFinding => f !== null),
      }
    : null;
  const controls = isRecord(raw.controls) ? raw.controls : null;
  const coverage = isRecord(raw.coverage) ? raw.coverage : null;
  const audit_summary = normalizeSummary(raw.audit_summary);
  const error = strOrNull(raw.error);

  if (!findings && !controls && !coverage && !audit_summary && !error) return null;

  return {
    job_id: str(raw.job_id),
    findings,
    controls,
    coverage,
    audit_summary,
    error,
  };
}
