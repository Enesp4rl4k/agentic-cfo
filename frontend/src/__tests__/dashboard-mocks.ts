/**
 * Mocks a dashboard page test needs and that do not differ between pages:
 * a Turkish organisation with the Turkey pack, and a link that is a plain anchor.
 * Used as the factory of vi.mock, which is hoisted, so it is imported inside it:
 *
 *   vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
 */
import React from "react";
import { vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export const orgSettingsModule = {
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    hasTrPack: true,
    focusMode: false,
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
};

export const nextLinkModule = {
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href, ...rest }, children),
};

/**
 * The payment-plan-change API as spies, shared by the pages that read or write it (/takvim, /onay):
 *
 *   vi.mock("@/lib/api/planChanges", async () => (await import("./dashboard-mocks")).planChangesModule);
 *   import { planChangeSpies } from "./dashboard-mocks";
 */
export const planChangeSpies = {
  listPlanChanges: vi.fn(),
  decidePlanChange: vi.fn(),
  withdrawPlanChange: vi.fn(),
  proposePlanChange: vi.fn(),
};

export const planChangesModule = {
  listPlanChanges: (...a: unknown[]) => planChangeSpies.listPlanChanges(...a),
  decidePlanChange: (...a: unknown[]) => planChangeSpies.decidePlanChange(...a),
  withdrawPlanChange: (...a: unknown[]) => planChangeSpies.withdrawPlanChange(...a),
  proposePlanChange: (...a: unknown[]) => planChangeSpies.proposePlanChange(...a),
  planChangeError: (e: unknown) => (e as { detail?: string })?.detail ?? null,
};

/**
 * The ledger API the approval pages read and write (/onay, and its one-tap queue), as spies:
 *
 *   vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
 *   const { getProposedSettlements, getPossibleDuplicates, resolveSettlement, resolveDuplicate } = ledgerSpies;
 */
export const ledgerSpies = {
  getProposedSettlements: vi.fn(),
  getPossibleDuplicates: vi.fn(),
  resolveSettlement: vi.fn(),
  resolveDuplicate: vi.fn(),
};

export const ledgerModule = {
  getProposedSettlements: (...a: unknown[]) => ledgerSpies.getProposedSettlements(...a),
  getPossibleDuplicates: (...a: unknown[]) => ledgerSpies.getPossibleDuplicates(...a),
  resolveSettlement: (...a: unknown[]) => ledgerSpies.resolveSettlement(...a),
  resolveDuplicate: (...a: unknown[]) => ledgerSpies.resolveDuplicate(...a),
};

/** A bank movement the ledger proposes to close an invoice with. */
export const settlementFixture = {
  id: "m1",
  amount_cents: 42_800_00,
  row: { id: "r1", transaction_date: "2026-11-12T00:00:00", amount_cents: 42_800_00, direction: "in", description: "Gelen havale 4410" },
  item: { counterparty: "Yıldız Tekstil", description: "Fatura A", amount_cents: 42_800_00, due_date: "2026-11-10" },
};

/** Renders a page inside a query client that does not retry, so a rejected call shows at once. */
export function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(React.createElement(QueryClientProvider, { client }, ui));
}
