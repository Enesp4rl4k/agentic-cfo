import { describe, expect, it } from "vitest";
import { normalizeCMOResult } from "@/lib/cmo-result";

/**
 * The wire shape the CMO pipeline actually emits — verified live on
 * 2026-10-14 (ROAS 3.9×, ₺18 CAC). Money is kuruş.
 */
const RAW = {
  job_id: "job-cmo-1",
  campaigns: {
    total_spend_cents: 5_000_000, // ₺50,000
    total_revenue_cents: 19_500_000, // ₺195,000 → ROAS 3.9
    total_conversions: 2_750,
    overall_roas: 3.9,
    overall_cac_cents: 1_800, // ₺18
    by_channel: {
      meta_ads: { spend_cents: 3_000_000, revenue_cents: 12_000_000, roas: 4.0, cac_cents: 1_700, conversions: 1_760, ctr: 0.031 },
      google_ads: { spend_cents: 2_000_000, revenue_cents: 7_500_000, roas: 3.75, cac_cents: 1_950, conversions: 990, ctr: 0.022 },
    },
    top_campaigns: [
      { name: "Yaz Kampanyası", channel: "meta_ads", spend_cents: 1_200_000, revenue_cents: 5_400_000, roas: 4.5, cac_cents: 1_500, status: "active" },
    ],
    underperforming: [
      { name: "Retargeting Q2", channel: "google_ads", spend_cents: 400_000, roas: 0.8, reason: "ROAS < 1.0" },
    ],
    alerts: [{ level: "medium", message: "Retargeting Q2 harcaması boşa gidiyor." }],
    narrative: "Kanal karması verimli.",
  },
  funnel: {
    total_leads: 5_000, mql_count: 1_500, sql_count: 600, won_count: 150,
    lead_to_mql_rate: 0.3, mql_to_sql_rate: 0.4, sql_to_won_rate: 0.25,
    overall_conversion_rate: 0.03, avg_cycle_days: 21,
    by_source: { ads: { leads: 3_200, mqls: 900, sqls: 350, won: 90, conversion_rate: 0.028 } },
    bottleneck_stage: "mql_to_sql",
    alerts: [], narrative: "",
  },
  cohorts: {
    cohorts_analyzed: 6, avg_retention_30d: 0.42, avg_retention_90d: 0.28,
    avg_ltv_cents: 2_400_000, avg_cac_cents: 18_000, ltv_cac_ratio: 133, churn_rate: 0.11,
    best_cohort: { period: "2026-03", retention_30d: 0.55, ltv_cents: 3_100_000 },
    worst_cohort: null,
    retention_trend: "improving", alerts: [], narrative: "",
  },
  cmo_summary: {
    overall_marketing_score: 7.4,
    growth_efficiency_score: 8.1,
    component_scores: { campaigns: 7.8, funnel: 6.9, cohorts: 7.2 },
    top_risks: [{ domain: "cfo", severity: "medium", message: "CAC trendi yükseliyor" }],
    quick_wins: [{ action: "Retargeting'i durdur", estimated_impact: "₺4k/ay", effort: "low" }],
    narrative: "Pazarlama verimli büyüyor.",
  },
  error: null,
};

describe("normalizeCMOResult", () => {
  it("maps the wire payload onto the dashboard view", () => {
    const v = normalizeCMOResult(RAW);
    expect(v).not.toBeNull();
    expect(v!.campaigns!.overall_roas).toBe(3.9);
    expect(v!.campaigns!.overall_cac_cents).toBe(1_800);
    expect(v!.campaigns!.by_channel.meta_ads.roas).toBe(4.0);
    expect(v!.campaigns!.underperforming).toHaveLength(1);
    expect(v!.funnel!.total_leads).toBe(5_000);
    expect(v!.cohorts!.ltv_cac_ratio).toBe(133);
    expect(v!.cohorts!.best_cohort!.period).toBe("2026-03");
    expect(v!.cmo_summary!.overall_marketing_score).toBe(7.4);
    expect(v!.cmo_summary!.component_scores.campaigns).toBe(7.8);
  });

  it("omits a section without its core metric instead of rendering undefined", () => {
    const v = normalizeCMOResult({ ...RAW, campaigns: { overall_roas: 3.9 } });
    expect(v!.campaigns).toBeUndefined();
    expect(v!.funnel).toBeDefined();
  });

  it("never leaks NaN from garbage numbers", () => {
    const v = normalizeCMOResult({
      campaigns: { total_spend_cents: NaN, overall_roas: "x" },
      cmo_summary: {
        overall_marketing_score: 7,
        component_scores: { campaigns: "bad", funnel: "6.5" },
      },
    });
    expect(v!.campaigns).toBeUndefined();
    // non-numeric scores are dropped, numeric strings still convert
    expect(v!.cmo_summary!.component_scores.campaigns).toBeUndefined();
    expect(v!.cmo_summary!.component_scores.funnel).toBe(6.5);
  });

  it("returns null for non-objects and empty payloads", () => {
    expect(normalizeCMOResult(undefined)).toBeNull();
    expect(normalizeCMOResult(null)).toBeNull();
    expect(normalizeCMOResult("boom")).toBeNull();
    expect(normalizeCMOResult({})).toBeNull();
  });

  it("keeps the error field so the view can show a failure honestly", () => {
    const v = normalizeCMOResult({ error: "CSV kolonları eşleşmedi" });
    expect(v!.error).toBe("CSV kolonları eşleşmedi");
    expect(v!.campaigns).toBeUndefined();
  });

  it("filters alert noise instead of rendering empty rows", () => {
    const v = normalizeCMOResult({
      campaigns: {
        total_spend_cents: 1,
        alerts: [{ level: "info" }, { message: "" }, "junk"],
      },
    });
    expect(v!.campaigns!.alerts).toEqual([]);
  });
});
