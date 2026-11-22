/**
 * A confirmed company profile may lead /onay with the one-tap button: a default, not a lock. The same
 * button and the same lists, only first; without a profile the page is as it was.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { ledgerSpies, planChangeSpies, renderWithQuery, settlementFixture as settlement } from "./dashboard-mocks";

vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
vi.mock("@/lib/api/planChanges", async () => (await import("./dashboard-mocks")).planChangesModule);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("@/lib/api/heldAnalyses", () => ({ listHeldAnalyses: async () => [], rejectAnalysis: vi.fn() }));
vi.mock("@/lib/api/heldRows", () => ({ listHeldRows: async () => [] }));
vi.mock("@/lib/api/agentReview", () => ({ getReviewQueue: async () => [], approveHeldJob: vi.fn(), rejectHeldJob: vi.fn() }));

const defaults = vi.hoisted(() => ({ value: null as null | { one_tap_first: boolean; briefing_to_smmm_suggested: boolean } }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, focusMode: false, sizeProfile: null,
    baseCurrency: "TRY", locale: "tr-TR", hasSmmm: null, profileDefaults: defaults.value,
  }),
}));

import OnayPage from "@/app/(dashboard)/onay/page";

/** Does the one-tap button come before the held-analyses block in the page? */
const leadsThePage = () => {
  const button = screen.getByRole("button", { name: "Tek dokunuşla karar ver" });
  const held = document.getElementById("analizler") as HTMLElement;
  return Boolean(held.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_PRECEDING);
};

beforeEach(() => {
  ledgerSpies.getProposedSettlements.mockReset();
  ledgerSpies.getPossibleDuplicates.mockReset();
  ledgerSpies.getProposedSettlements.mockResolvedValue([settlement]);
  ledgerSpies.getPossibleDuplicates.mockResolvedValue([]);
  planChangeSpies.listPlanChanges.mockReset();
  planChangeSpies.listPlanChanges.mockResolvedValue({ changes: [], canDecide: false, selfDecisionAck: "" });
});

describe("/onay: profile defaults", () => {
  it("puts the one-tap button before the lists when the profile says so", async () => {
    defaults.value = { one_tap_first: true, briefing_to_smmm_suggested: true };
    renderWithQuery(<OnayPage />);
    await screen.findByRole("button", { name: "Tek dokunuşla karar ver" });
    expect(leadsThePage()).toBe(true);
  });

  it("keeps it below the lists without one, and the button is the same", async () => {
    defaults.value = null;
    renderWithQuery(<OnayPage />);
    await screen.findByRole("button", { name: "Tek dokunuşla karar ver" });
    expect(leadsThePage()).toBe(false);
    expect(screen.getByRole("button", { name: "Evet, bu fatura" })).toBeInTheDocument();
  });
});
