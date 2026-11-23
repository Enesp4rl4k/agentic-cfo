/**
 * The cross-agent insights hold no runway threshold of their own: the class is the server's
 * (`forecast.runway.level`), so a runway that is not measured, or has no class, fires none of the runway rules.
 */
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CrossAgentIntelligence } from "@/components/ui/cross-agent-intelligence";

const context = (runway: Record<string, unknown> | null) =>
  ({
    last_cfo_result: { cashflow: { operating: -100 }, forecast: { scenarios: { base: { runway_months: 2 } }, runway } },
    last_chro_result: { headcount: { total_headcount: 12 }, attrition: { annualized_attrition_rate: 0.3 } },
    last_cto_result: null, last_cmo_result: null, last_risk_result: null,
  }) as never;

const show = (runway: Record<string, unknown> | null) =>
  render(<CrossAgentIntelligence context={context(runway)} onAskChat={() => {}} />);

describe("cross-agent runway rules", () => {
  it("fires on the server's class and takes its severity from it", () => {
    show({ status: "computed", level: "warning", runway_months: 2.5 });
    expect(screen.getByText("Nakit Yakma Uyarısı")).toBeTruthy();
    expect(screen.getByText(/2\.5 aylık runway/)).toBeTruthy();
  });

  it("fires none when the runway has no class or is not measured, whatever the scenario number says", () => {
    show({ status: "no_balance", level: null, runway_months: null });
    expect(screen.queryByText("Nakit Yakma Uyarısı")).toBeNull();
    expect(screen.queryByText("İşe Alım Dondurma Sinyali")).toBeNull();
  });
});
