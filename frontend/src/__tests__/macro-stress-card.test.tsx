/**
 * V2 — the macro stress card tells the truth.
 *
 * - The EUR slider sends its own value (it used to send the USD value).
 * - No CFO analysis → an honest empty state, never numbers for a made-up company.
 * - The simulation is badged "Tahmin"; the static TCMB fallback is "Benchmark".
 * - Risk and recommendations arrive as codes and are worded from the message tree.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { client } = vi.hoisted(() => ({
  client: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Örnek A.Ş.", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));

import { getMessages } from "@/lib/i18n";
import { MacroStressTestCard } from "@/components/macro/MacroStressTestCard";

const tr = getMessages("tr");

const MACRO = {
  usd_try: 34.12,
  eur_try: 37.05,
  policy_rate_pct: 45,
  inflation_pct: 61.8,
  data_source: "static_fallback",
};

const RESULT = {
  baseline_runway_months: 8,
  stressed_runway_months: 6.2,
  runway_delta_months: -1.8,
  monthly_cost_increase_lira: 2500,
  monthly_net_after_shock_lira: -12500,
  months_observed: 12,
  risk_level: "HIGH",
  recommendations: ["fx_hedge"],
  data_source: "estimated",
  assumptions: { fx_exposure_ratio: 0.25, working_capital_debt_months: 2 },
};

function respond(simulation: typeof RESULT | null) {
  client.get.mockResolvedValue({ data: { data: MACRO } });
  client.post.mockResolvedValue({
    data: {
      data: {
        current_macro: MACRO,
        simulation_result: simulation,
        baseline_missing_reason: simulation ? null : "no_cfo_analysis",
      },
    },
  });
}

afterEach(() => vi.clearAllMocks());

describe("MacroStressTestCard", () => {
  it("shows an honest empty state when there is no CFO analysis", async () => {
    respond(null);
    render(<MacroStressTestCard />);

    expect(await screen.findByText(tr.macroStress.noBaseline)).toBeTruthy();
    expect(screen.queryByText(tr.macroStress.stressedRunway)).toBeNull();
  });

  it("sends the EUR slider's own value, not the USD one", async () => {
    respond(RESULT);
    render(<MacroStressTestCard />);
    await screen.findByText(tr.macroStress.stressedRunway);

    fireEvent.change(screen.getByLabelText(tr.macroStress.eurShock), {
      target: { value: "40" },
    });

    await waitFor(() => {
      const last = client.post.mock.calls.at(-1);
      expect(last?.[1]).toMatchObject({ usd_shock_pct: 15, eur_shock_pct: 40 });
    });
  });

  it("words risk and recommendations from the message tree and badges provenance", async () => {
    respond(RESULT);
    render(<MacroStressTestCard />);

    expect(await screen.findByText(tr.macroStress.risk.HIGH)).toBeTruthy();
    expect(screen.getByText(tr.macroStress.recs.fx_hedge)).toBeTruthy();
    expect(screen.getByText(tr.provenance.estimated)).toBeTruthy();
    // Static TCMB fallback is a fixed reference, never shown as a live reading.
    expect(screen.getByText(tr.provenance.benchmark)).toBeTruthy();
    expect(screen.queryByText(tr.provenance.real)).toBeNull();
  });

  it("shows 'no limit' instead of inventing a runway for a profitable forecast", async () => {
    respond({ ...RESULT, baseline_runway_months: null as unknown as number,
      stressed_runway_months: null as unknown as number,
      runway_delta_months: null as unknown as number, risk_level: "LOW" });
    render(<MacroStressTestCard />);

    expect(await screen.findByText(tr.macroStress.noRunwayLimit)).toBeTruthy();
    expect(screen.queryByText(tr.macroStress.runwayDelta)).toBeNull();
  });
});
