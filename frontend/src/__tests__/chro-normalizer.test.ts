import { describe, expect, it } from "vitest";
import { normalizeCHROResult, type RawCHROResult } from "@/lib/chro-result";

/**
 * The wire shape the CHRO agents actually emit — keys pinned by
 * backend/tests/test_agents/test_chro_pipeline.py.
 */
const RAW: RawCHROResult = {
  job_id: "job-1",
  headcount: {
    total_headcount: 10,
    total_fte: 9.8,
    avg_tenure_years: 3.4,
    recently_hired_count: 4,
    by_department: { Engineering: 5, Sales: 3, Support: 2 },
    alerts: [{ level: "info", message: "Hiring pace is healthy" }],
    narrative: "Başlık narrative",
  },
  attrition: {
    total_departures: 5,
    involuntary_departures_count: 1,
    early_departure_rate: 0.2,
    estimated_replacement_cost: 375_000_000, // kuruş → ₺3.75M
    attrition_reasons: { better_offer: 3, performance: 2 },
    alerts: [],
    narrative: "Ayrılma narrative",
  },
  compensation: {
    total_employees: 10,
    total_annual_salary: 150_000_000, // kuruş → ₺1.5M
    total_annual_benefits: 30_000_000,
    total_annual_comp: 180_000_000,
    total_equity_shares: 120_000, // equity stays raw (lira), not kuruş
    below_market_count: 2,
    above_market_count: 1,
    avg_salary_by_level: { senior: 22_000_000, junior: 9_000_000 },
    alerts: [],
    narrative: "Ücret narrative",
  },
  chro_summary: {
    chro_health_score: 5.2,
    component_scores: { headcount_org_health: 9, attrition_health: 8.4 },
    top_risks: [{ title: "Kısa başlık", severity: "critical", description: "Risk açıklaması" }],
    quick_wins: [{ action: "Eylem", effort: "orta", impact: "Etki" }],
    narrative: "Özet narrative",
  },
  error: null,
};

describe("normalizeCHROResult", () => {
  it("maps the backend keys onto the dashboard view", () => {
    const view = normalizeCHROResult(RAW);
    expect(view).not.toBeNull();
    expect(view!.headcount!.total_headcount).toBe(10);
    expect(view!.headcount!.total_fte).toBe(9.8);
    expect(view!.headcount!.recent_hires).toBe(4);
    expect(view!.headcount!.by_department).toEqual([
      { dept: "Engineering", count: 5 },
      { dept: "Sales", count: 3 },
      { dept: "Support", count: 2 },
    ]);
    // net change = recent hires − departures
    expect(view!.headcount!.net_change).toBe(-1);
  });

  it("turns attrition counters into the labeled figures", () => {
    const view = normalizeCHROResult(RAW)!;
    expect(view.attrition!.total_departures).toBe(5);
    expect(view.attrition!.voluntary).toBe(4); // 5 − 1 involuntary
    expect(view.attrition!.early_rate).toBe(0.2);
    expect(view.attrition!.cost).toBe(3_750_000); // kuruş → lira
    expect(view.attrition!.top_reasons).toEqual([
      { reason: "better_offer", count: 3, pct: 60 },
      { reason: "performance", count: 2, pct: 40 },
    ]);
  });

  it("converts compensation money to lira and percents to ratios", () => {
    const view = normalizeCHROResult(RAW)!;
    const comp = view.compensation!;
    expect(comp.total_payroll).toBe(1_800_000);
    expect(comp.avg_salary).toBe(150_000);
    expect(comp.benefits_cost).toBe(300_000);
    expect(comp.equity_burn).toBe(120_000);
    expect(comp.below_market_pct).toBeCloseTo(0.2);
    expect(comp.above_market_pct).toBeCloseTo(0.1);
    // level headcounts cross-filled from the headcount section
    expect(comp.by_level).toEqual([
      { level: "senior", avg_salary: 220_000, count: null },
      { level: "junior", avg_salary: 90_000, count: null },
    ]);
  });

  it("reads the summary the pipeline emits", () => {
    const view = normalizeCHROResult(RAW)!;
    expect(view.summary!.score).toBe(5.2);
    expect(view.summary!.top_risks).toEqual([
      { severity: "critical", message: "Risk açıklaması" },
    ]);
    expect(view.summary!.quick_wins[0]).toEqual({
      action: "Eylem",
      impact: "Etki",
      effort: "medium",
    });
  });

  it("leaves metrics the pipeline cannot produce as null", () => {
    const view = normalizeCHROResult({ headcount: { total_headcount: 3 } })!;
    expect(view.headcount!.total_fte).toBeNull();
    expect(view.headcount!.avg_tenure_years).toBeNull();
    expect(view.headcount!.net_change).toBeNull(); // no attrition section
    expect(view.attrition).toBeNull();
    expect(view.compensation).toBeNull();
    expect(view.summary).toBeNull();
  });

  it("returns null when there is nothing to render", () => {
    expect(normalizeCHROResult(null)).toBeNull();
    expect(normalizeCHROResult(undefined)).toBeNull();
    expect(normalizeCHROResult({})).toBeNull();
  });

  it("keeps a pipeline error visible even without sections", () => {
    const view = normalizeCHROResult({ error: "boom" })!;
    expect(view.error).toBe("boom");
    expect(view.headcount).toBeNull();
  });
});
