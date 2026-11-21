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
    sizeProfile: null,
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
  getCashRadar: vi.fn(),
  getMondayBriefing: vi.fn().mockResolvedValue(null),
  respondToMondayBriefing: vi.fn(),
};

export const ledgerModule = {
  getProposedSettlements: (...a: unknown[]) => ledgerSpies.getProposedSettlements(...a),
  getPossibleDuplicates: (...a: unknown[]) => ledgerSpies.getPossibleDuplicates(...a),
  resolveSettlement: (...a: unknown[]) => ledgerSpies.resolveSettlement(...a),
  resolveDuplicate: (...a: unknown[]) => ledgerSpies.resolveDuplicate(...a),
  getCashRadar: (...a: unknown[]) => ledgerSpies.getCashRadar(...a),
  getMondayBriefing: (...a: unknown[]) => ledgerSpies.getMondayBriefing(...a),
  respondToMondayBriefing: (...a: unknown[]) => ledgerSpies.respondToMondayBriefing(...a),
};

/** The radar's "how well is this known" parts of a week with nothing estimated, and a fresh opening balance. */
export const noBasis = { known_cents: 0, estimated_cents: 0, assumed_cents: 0 };
export const openingCashFixture = {
  balance_cents: 100_000_00,
  as_of: "2025-01-01",
  age_days: 0,
  stale: false,
  stale_after_days: 7,
  source_job_id: "j1",
  source_filename: "ekstre.csv",
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

/**
 * The Monday briefing's delivery API and the memberships (whose active role decides who may release),
 * as spies. `membershipsFor("smmm")` / `membershipsFor("owner")` is what /org/memberships answers.
 *
 *   vi.mock("@/lib/api/briefing", async () => (await import("./dashboard-mocks")).briefingDeliveryModule);
 *   vi.mock("@/lib/api/orgs", async () => (await import("./dashboard-mocks")).orgsModule);
 */
export const briefingDeliverySpies = {
  getBriefingDeliveries: vi.fn(),
  releaseMondayBriefing: vi.fn(),
};

export const briefingDeliveryModule = {
  getBriefingDeliveries: (...a: unknown[]) => briefingDeliverySpies.getBriefingDeliveries(...a),
  releaseMondayBriefing: (...a: unknown[]) => briefingDeliverySpies.releaseMondayBriefing(...a),
};

export const membershipSpies = { getMemberships: vi.fn() };

export const orgsModule = { getMemberships: (...a: unknown[]) => membershipSpies.getMemberships(...a) };

export const membershipsFor = (role: string) => ({
  active_org_id: "org1",
  memberships: [{ org_id: "org1", name: "Test Org", role, active: true }],
});

/**
 * The held-rows API (rows the system would not book alone) as spies:
 *
 *   vi.mock("@/lib/api/heldRows", async () => (await import("./dashboard-mocks")).heldRowsModule);
 *   import { heldRowsSpies } from "./dashboard-mocks";
 */
export const heldRowsSpies = {
  listHeldRows: vi.fn().mockResolvedValue([]),
  releaseHeldRows: vi.fn().mockResolvedValue(undefined),
  rejectHeldRows: vi.fn().mockResolvedValue(undefined),
  getBaseCurrency: vi.fn().mockResolvedValue({ currency: null, confirmed: false, waiting_for_currency: 0 }),
  confirmBaseCurrency: vi.fn().mockResolvedValue(undefined),
  listFileQuestions: vi.fn().mockResolvedValue({ files: [], canRemember: true }),
  answerFileDirection: vi.fn().mockResolvedValue(undefined),
  listDirectionMappings: vi.fn().mockResolvedValue([]),
  revokeDirectionMapping: vi.fn().mockResolvedValue(undefined),
};

export const heldRowsModule = {
  listHeldRows: (...a: unknown[]) => heldRowsSpies.listHeldRows(...a),
  releaseHeldRows: (...a: unknown[]) => heldRowsSpies.releaseHeldRows(...a),
  rejectHeldRows: (...a: unknown[]) => heldRowsSpies.rejectHeldRows(...a),
  getBaseCurrency: (...a: unknown[]) => heldRowsSpies.getBaseCurrency(...a),
  confirmBaseCurrency: (...a: unknown[]) => heldRowsSpies.confirmBaseCurrency(...a),
  listFileQuestions: (...a: unknown[]) => heldRowsSpies.listFileQuestions(...a),
  answerFileDirection: (...a: unknown[]) => heldRowsSpies.answerFileDirection(...a),
  listDirectionMappings: (...a: unknown[]) => heldRowsSpies.listDirectionMappings(...a),
  revokeDirectionMapping: (...a: unknown[]) => heldRowsSpies.revokeDirectionMapping(...a),
};

/** A row held because its confidence is unknown, and one held because it has no currency, both from one upload. */
export const heldRowFixture = {
  id: "h1",
  job_id: "j1",
  source: { job_id: "j1", filename: "mart.csv", document_id: null },
  reasons: ["confidence_unknown"],
  reason_labels: ["güven bilinmiyor"],
  confidence: null,
  amount_cents: 150_000,
  currency: "TRY",
  type: "expense",
  description: "Elektrik faturası",
  vendor: null,
  transaction_date: "2026-03-15",
  document_id: null,
  currency_assumed: false,
  direction_file: null,
};

export const heldNoCurrencyFixture = {
  ...heldRowFixture,
  id: "h2",
  reasons: ["currency_unknown"],
  reason_labels: ["para birimi bilinmiyor"],
  confidence: 0.95,
  currency: null,
  description: "Kira",
};

/** A statement whose amounts are all positive with no column saying which way they went: one question for the file. */
export const fileQuestionFixture = {
  job_id: "j9",
  file_key: "f9",
  reason: "no_signal",
  rows: 2,
  options: ["mixed", "only_expense", "only_income"],
  question: {
    columns: [
      { name: "tarih", role: "date" },
      { name: "açıklama", role: "description" },
      { name: "tutar", role: "amount" },
    ],
    samples: [
      { date: "01.03.2026", description: "Kira", amount: "1500" },
      { date: "02.03.2026", description: "Elektrik", amount: "250" },
    ],
  },
};

export const directionMappingFixture = {
  id: "m9",
  signature: "abc",
  reason: "convention_unverified",
  answer: "inverted",
  columns: "tarih, açıklama, tutar",
  created_at: "2026-03-05T10:00:00+00:00",
};
