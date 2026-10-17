import { describe, it, expect } from "vitest";
import { normalizeAuditResult, type AuditResultView } from "@/lib/audit-result";

describe("normalizeAuditResult", () => {
  it("maps the audit wire shape: typed findings rows, summary scores, passthrough sections", () => {
    const view = normalizeAuditResult({
      job_id: "a-1",
      findings: {
        top_overdue: [
          {
            finding_id: "F-1",
            title: "VKN maskelenmesi açık",
            severity: "high",
            status: "open",
            due_date: "2026-09-01",
            owner: "CFO",
            category: "veri",
            remediation_status: "in_progress",
            days_overdue: 43,
          },
          { title: "", severity: "low" },
          "bozuk-satır",
        ],
      },
      controls: { rows: 12 },
      coverage: { pct: 0.91 },
      audit_summary: {
        overall_audit_score: 74,
        audit_maturity: "defined",
        component_scores: { access: 80, change: "n/a", backup: 61 },
        top_risks: [{ domain: "access", severity: "medium", message: "KVKK erişim gözden geçirmesi gecikti" }, { message: "" }],
        quick_wins: [{ action: "Erişim gözden geçirme", estimated_impact: "orta", effort: "düşük" }],
        narrative: "Denetim olgunluğu defined seviyesinde.",
      },
      error: null,
    });

    expect(view).not.toBeNull();
    const v = view as AuditResultView;
    expect(v.findings?.top_overdue).toHaveLength(1);
    expect(v.findings?.top_overdue[0].days_overdue).toBe(43);
    expect(v.controls).toEqual({ rows: 12 });
    expect(v.coverage).toEqual({ pct: 0.91 });
    expect(v.audit_summary?.overall_audit_score).toBe(74);
    // non-numeric component dropped, empty message dropped
    expect(v.audit_summary?.component_scores).toEqual({ access: 80, backup: 61 });
    expect(v.audit_summary?.top_risks).toHaveLength(1);
    expect(v.audit_summary?.quick_wins).toHaveLength(1);
    expect(v.error).toBeNull();
  });

  it("returns null for non-objects and empty payloads", () => {
    expect(normalizeAuditResult(null)).toBeNull();
    expect(normalizeAuditResult(42)).toBeNull();
    expect(normalizeAuditResult({ job_id: "a" })).toBeNull();
  });

  it("nulls the summary when the score is garbage instead of showing NaN", () => {
    const v = normalizeAuditResult({ findings: { top_overdue: [] }, audit_summary: { overall_audit_score: "n/a" } });
    expect(v?.audit_summary).toBeNull();
    expect(v?.findings).toEqual({ top_overdue: [] });
  });

  it("keeps error-only payloads", () => {
    const v = normalizeAuditResult({ error: "findings CSV okunamadı" });
    expect(v?.error).toBe("findings CSV okunamadı");
    expect(v?.findings).toBeNull();
  });
});
