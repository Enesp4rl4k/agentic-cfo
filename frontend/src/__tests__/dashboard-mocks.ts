/**
 * Mocks a dashboard page test needs and that do not differ between pages:
 * a Turkish organisation with the Turkey pack, and a link that is a plain anchor.
 * Used as the factory of vi.mock, which is hoisted, so it is imported inside it:
 *
 *   vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
 */
import React from "react";
import { vi } from "vitest";

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
