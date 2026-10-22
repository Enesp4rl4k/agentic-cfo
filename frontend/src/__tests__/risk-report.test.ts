import { describe, it, expect } from "vitest";
import { normalizeRiskCascadeReport } from "@/lib/risk-report";

describe("normalizeRiskCascadeReport", () => {
  it("maps the risk wire shape with honest nulls and coerces unknown enums", () => {
    const report = normalizeRiskCascadeReport({
      kri_posture: {
        kri_score: 6,
        posture: "elevated",
        posture_tr: "Elevated",
        counts: "bozuk",
        all_kris: [
          {
            name: "DSO",
            category: "financial",
            current_value: 52,
            unit: "gün",
            threshold_amber: 45,
            threshold_red: 60,
            higher_is_worse: true,
            status: "amber",
            trend: "deteriorating",
            trajectory_months: 3,
            source: "CFO report",
            evidence: "rapor_satırı",
            cascade_trigger: "nakit",
            cascade_params: { days: 60 },
          },
          {
            name: "Churn",
            current_value: "n/a",
            status: "purple", // bilinmeyen — asla yeşil sakin değil
            trend: "wat", // ölçülmedi → null (ok yok)
            threshold_amber: "x",
          },
          { name: "" }, // adsız — düşer
          "bozuk-satır",
        ],
        red_kris: [],
        amber_kris: [{ name: "DSO", status: "amber" }],
        upcoming_red: [],
        cascade_ready: [],
        by_category: { financial: [{ name: "DSO" }], broken: "not-a-list" },
        sources: ["CFO raporu", 42],
      },
      cascade_links: [
        {
          kri_name: "DSO",
          kri_status: "amber",
          kri_value: "52.5",
          trigger_type: "threshold",
          cascade_result: { domain: "treasury" },
          cascade_error: null,
        },
        { kri_name: "" },
      ],
      total_cascades: "2",
      critical_count: null,
      cascade_summary: "DSO → tahsilat gecikmesi",
      domains_at_risk: ["treasury", 7],
      top_cascade: { kri_name: "DSO", trigger_type: "threshold", cascade_result: { a: 1 } },
    });

    expect(report).not.toBeNull();
    const p = report!.kri_posture!;
    // counts: wire garbage → all_kris'ten türetilmiş
    expect(p.counts).toEqual({ red: 0, amber: 2, green: 0, total: 2 });
    expect(p.all_kris).toHaveLength(2);
    expect(p.all_kris[0].current_value).toBe(52);
    expect(p.all_kris[0].trend).toBe("deteriorating");
    expect(p.all_kris[1].current_value).toBeNull(); // ölçülmeyen → "—"
    expect(p.all_kris[1].status).toBe("amber"); // bilinmeyen durum → görünür, yeşil değil
    expect(p.all_kris[1].trend).toBeNull();
    expect(p.all_kris[1].threshold_amber).toBeNull();
    expect(p.by_category.financial).toHaveLength(1);
    expect(p.by_category.financial[0].name).toBe("DSO");
    expect(p.by_category.broken).toEqual([]);
    expect(p.sources).toEqual(["CFO raporu"]);
    // cascade links
    expect(report!.cascade_links).toHaveLength(1);
    expect(report!.cascade_links[0].kri_value).toBe(52.5);
    expect(report!.total_cascades).toBe(2);
    expect(report!.critical_count).toBe(0);
    expect(report!.domains_at_risk).toEqual(["treasury"]);
    expect(report!.top_cascade).not.toBeNull();
  });

  it("returns null for non-objects and empty payloads", () => {
    expect(normalizeRiskCascadeReport(null)).toBeNull();
    expect(normalizeRiskCascadeReport("boom")).toBeNull();
    expect(normalizeRiskCascadeReport({})).toBeNull();
    expect(normalizeRiskCascadeReport({ kri_posture: "x" })).toBeNull();
  });

  it("keeps a posture-only payload and marks missing posture honest (null, not calm)", () => {
    const report = normalizeRiskCascadeReport({
      kri_posture: {
        kri_score: null,
        posture: "calm", // geçersiz → no_data
        posture_tr: "Stabil",
        all_kris: [],
        counts: { red: 99, total: "x" }, // total türetilir, red wire'dan
      },
      cascade_links: [],
      total_cascades: 0,
      critical_count: 0,
      cascade_summary: "",
      domains_at_risk: [],
      top_cascade: null,
    });
    expect(report).not.toBeNull();
    const p = report!.kri_posture!;
    expect(p.posture).toBe("no_data");
    expect(p.kri_score).toBeNull();
    expect(p.counts.red).toBe(99);
    expect(p.counts.total).toBe(0);
    expect(p.by_category).toEqual({});
    expect(p.sources).toEqual([]);
  });
});
