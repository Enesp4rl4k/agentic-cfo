import { describe, it, expect } from "vitest";
import { normalizeCEOResult, type CEOView } from "@/lib/ceo-result";

describe("normalizeCEOResult", () => {
  it("maps the CEO orchestrator wire shape (title-bearing cross_risks, list domains)", () => {
    const view = normalizeCEOResult({
      job_id: "j-1",
      cross_risks: [
        {
          risk_id: "R-1",
          title: "Nakit açığı tech roadmap'ini kilitleyebilir",
          severity: "high",
          domains: ["finance", "tech"],
          recommended_action: "13. hafta planını dondur",
        },
      ],
      swot: {
        strengths: ["Nakit disiplini"],
        weaknesses: ["Tek müşteri bağımlılığı"],
        opportunities: [],
        threats: ["Kur oynaklığı"],
        strategic_priorities: ["Gelir çeşitlendirmesi"],
      },
      board_deck: [
        { slide_number: 1, title: "Yönetici Özeti", content: "Q1", metrics: { net_income_cents: 123456 } },
        { slide_number: 2, title: "", content: "başlıksız — düşer" },
      ],
      okr_status: {
        company_score: 81,
        objectives: [
          {
            objective_id: "o1",
            name: "Nakit dönüşümü",
            weight: 0.4,
            score: 0.7,
            momentum: "up",
            key_results: [{ name: "DSO < 45", progress: 0.6 }],
          },
          { name: "", weight: "garbage" },
        ],
      },
      outlook: { base_case: [1, 2, "3"], optimistic: ["x", 4], pessimistic: null },
      financial_summary: { revenue_cents: 100, net_margin: "0.12", junk: "not-a-number" },
      strategic_priorities: [{ title: "Fiyatlandırma", rationale: "Marj", horizon: "Q2", owner: "CEO", metric: "%", target_date: "2026-06" }],
      decision_brief: { id: "db-1" },
      error: null,
    });

    expect(view).not.toBeNull();
    const v = view as CEOView;
    // cross_risks: title → description, domains[0] → domain (honest alias)
    expect(v.cross_risks).toHaveLength(1);
    expect(v.cross_risks[0].description).toBe("Nakit açığı tech roadmap'ini kilitleyebilir");
    expect(v.cross_risks[0].domain).toBe("finance");
    expect(v.cross_risks[0].risk_type).toBe("R-1");
    expect(v.cross_risks[0].severity).toBe("high");
    // swot
    expect(v.swot?.strengths).toEqual(["Nakit disiplini"]);
    expect(v.swot?.strategic_priorities).toEqual(["Gelir çeşitlendirmesi"]);
    // board deck: empty title dropped
    expect(v.board_deck).toHaveLength(1);
    expect(v.board_deck[0].metrics).toEqual({ net_income_cents: 123456 });
    // okr: garbage row dropped, momentum fallback
    expect(v.okr_status?.company_score).toBe(81);
    expect(v.okr_status?.objectives).toHaveLength(1);
    // outlook: non-numeric entries dropped, series kept
    expect(v.outlook).toEqual({ base_case: [1, 2, 3], optimistic: [4], pessimistic: [] });
    // financial_summary: numbers only
    expect(v.financial_summary).toEqual({ revenue_cents: 100, net_margin: 0.12 });
    expect(v.strategic_priorities[0].title).toBe("Fiyatlandırma");
    expect(v.decision_brief).not.toBeNull();
  });

  it("returns null for non-objects and for payloads without any visible section", () => {
    expect(normalizeCEOResult(null)).toBeNull();
    expect(normalizeCEOResult("boom")).toBeNull();
    expect(normalizeCEOResult([])).toBeNull();
    expect(normalizeCEOResult({ job_id: "j", board_deck: "not-a-list" })).toBeNull();
  });

  it("keeps an error-only payload so the view can say so", () => {
    const v = normalizeCEOResult({ error: "CEO orchestrator timeout" });
    expect(v?.error).toBe("CEO orchestrator timeout");
    expect(v?.board_deck).toEqual([]);
    expect(v?.cross_risks).toEqual([]);
  });

  it("drops cross-risks with neither title, description nor action", () => {
    const v = normalizeCEOResult({ cross_risks: [{ severity: "high", domains: [] }] });
    expect(v).toBeNull();
  });

  it("rejects summary-with-garbage honesty (NaN company_score → null okr_status)", () => {
    const v = normalizeCEOResult({ okr_status: { company_score: "n/a", objectives: [] } });
    expect(v).toBeNull();
  });
});
