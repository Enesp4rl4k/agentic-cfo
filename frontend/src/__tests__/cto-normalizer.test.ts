import { describe, expect, it } from "vitest";
import { normalizeCTOResult } from "@/lib/cto-result";

/**
 * The wire shape the CTO pipeline actually emits — verified live on
 * 2026-10-14; section shapes pinned by components/cto/types.ts and the
 * backend CTO agent tests.
 */
const RAW = {
  job_id: "job-cto-1",
  infra: {
    total_cost_cents: 12_500_000, // kuruş → ₺125,000
    waste_estimate_cents: 1_800_000,
    mom_change_pct: 4.2,
    top_cost_drivers: [{ service: "ec2-prod", cost_cents: 6_000_000, pct: 48 }],
    by_environment: { prod: 9_700_000, staging: 2_800_000 },
    alerts: [{ level: "critical", message: "Non-production spend ₺28,000/month" }],
    narrative: "Bulut harcaması artıyor.",
  },
  tech_debt: {
    total_commits: 120,
    active_contributors: 7,
    churn_rate: 0.12,
    debt_score: 4.0,
    hotspot_files: [{ file: "billing.py", changes: 42, authors: 3, bus_factor_risk: true }],
    refactor_priorities: [],
    narrative: "Churn yüksek.",
  },
  incidents: {
    total_incidents: 3,
    by_severity: { major: 1, minor: 2 },
    mttr_hours: 2.5,
    mttd_hours: 1.1,
    sla_breach_count: 1,
    sla_breach_pct: 12,
    recurring_services: [],
    trend: "down",
    alerts: [],
    narrative: "",
  },
  velocity: {
    sprints_analyzed: 6,
    avg_velocity: 34,
    velocity_trend: "up",
    predictability_score: 0.8,
    carryover_ratio: 0.1,
    bottlenecks: [],
    sprint_series: [],
    narrative: "",
  },
  cto_summary: {
    overall_health_score: 2.0,
    component_scores: { infra: 2, tech_debt: 4, incidents: 1, velocity: 5 },
    top_risks: [{ domain: "cfo", severity: "critical", message: "Runway risk" }],
    quick_wins: [{ action: "Pause staging", estimated_impact: "₺28k/ay", effort: "düşük" }],
    narrative: "Altyapı sağlığı kritik.",
  },
  awaiting_review: false,
  min_confidence: 0.8,
  error: null,
};

describe("normalizeCTOResult", () => {
  it("maps the wire payload onto the typed view", () => {
    const v = normalizeCTOResult(RAW);
    expect(v).not.toBeNull();
    expect(v!.job_id).toBe("job-cto-1");
    expect(v!.infra!.total_cost_cents).toBe(12_500_000);
    expect(v!.infra!.waste_estimate_cents).toBe(1_800_000);
    expect(v!.infra!.by_environment.prod).toBe(9_700_000);
    expect(v!.infra!.alerts).toHaveLength(1);
    expect(v!.tech_debt!.debt_score).toBe(4.0);
    expect(v!.tech_debt!.hotspot_files[0].bus_factor_risk).toBe(true);
    expect(v!.incidents!.mttr_hours).toBe(2.5);
    expect(v!.velocity!.avg_velocity).toBe(34);
    expect(v!.cto_summary!.overall_health_score).toBe(2.0);
    expect(v!.cto_summary!.component_scores.infra).toBe(2);
    // the pipeline writes quick-win effort in Turkish
    expect(v!.cto_summary!.quick_wins[0].effort).toBe("low");
    expect(v!.awaiting_review).toBe(false);
    expect(v!.min_confidence).toBe(0.8);
  });

  it("turns a section without its core metric into null, not undefined", () => {
    const v = normalizeCTOResult({ ...RAW, infra: { waste_estimate_cents: 100 } });
    expect(v!.infra).toBeNull();
  });

  it("never leaks NaN from garbage numbers", () => {
    const v = normalizeCTOResult({
      cto_summary: { overall_health_score: NaN, component_scores: { infra: "x" } },
      incidents: { total_incidents: 3, mttr_hours: "abc", sla_breach_count: null },
    });
    expect(v!.cto_summary).toBeNull();
    expect(v!.incidents!.mttr_hours).toBeNull();
    expect(v!.incidents!.sla_breach_count).toBe(0);
  });

  it("returns null for non-objects and empty payloads", () => {
    expect(normalizeCTOResult(undefined)).toBeNull();
    expect(normalizeCTOResult(null)).toBeNull();
    expect(normalizeCTOResult("error")).toBeNull();
    expect(normalizeCTOResult({})).toBeNull();
  });

  it("keeps the error field so the view can show a failure honestly", () => {
    const v = normalizeCTOResult({ error: "CSV okunamadı" });
    expect(v!.error).toBe("CSV okunamadı");
    expect(v!.infra).toBeNull();
  });

  it("filters alert noise instead of rendering empty rows", () => {
    const v = normalizeCTOResult({
      infra: {
        total_cost_cents: 1,
        alerts: [{ level: "info" }, { level: 42, message: "" }, "junk"],
      },
    });
    expect(v!.infra!.alerts).toEqual([]);
  });
});
