/**
 * A currency we do not know is never drawn with a symbol: not as dollars (the old Intl fallback), not as
 * lira. It is the plain number and an explicit "currency unknown" label.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { client } = vi.hoisted(() => ({ client: { get: vi.fn(), post: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({ apiClient: client }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "org1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false,
    error: null,
    refresh: () => {},
    baseCurrency: "TRY",
    locale: "tr-TR",
  }),
}));

import { LedgerCard } from "@/components/command-center/LedgerCard";
import { OtherCurrencyLines } from "@/components/ui/other-currency-lines";
import { formatCurrency } from "@/lib/utils";

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

afterEach(() => vi.clearAllMocks());

describe("formatCurrency with a code that is not a currency", () => {
  it.each(["?", "", "   ", "XX1", "TL"])("shows %j as a plain number and says it is unknown", (code) => {
    const out = formatCurrency(1234, code, "tr-TR");
    expect(out).toMatch(/1\.234/);
    expect(out).not.toMatch(/[$₺€£]|USD|TRY/);
    expect(out).toContain("currency unknown");
  });

  it("takes the label from the caller so each locale can say it", () => {
    expect(formatCurrency(5, "?", "tr-TR", "para birimi bilinmiyor")).toContain("para birimi bilinmiyor");
  });

  it("still formats a real code with its symbol", () => {
    expect(formatCurrency(1234, "USD", "en-US")).toBe("$1,234");
  });
});

describe("components with an unknown currency", () => {
  it("OtherCurrencyLines does not show dollars or a question mark", () => {
    const { container } = wrap(
      <OtherCurrencyLines base="TRY" items={[{ currency: "?", revenue_cents: 0, expense_cents: 1_240_000 }]} />,
    );
    expect(container.textContent).toMatch(/12\.400/);
    expect(container.textContent).toContain("para birimi bilinmiyor");
    expect(container.textContent).not.toMatch(/[$₺]|\?/);
  });

  it("LedgerCard shows an unknown-currency subtotal without a symbol", async () => {
    client.get.mockImplementation((url: string) => {
      if (url === "/ledger/summary") {
        return Promise.resolve({
          data: {
            data: {
              last_upload: null,
              open_items: { receivable_cents: 0, payable_cents: 0, no_due_date: 0, other_currency: 0 },
              rows: 3, currency: null, base_state: "ambiguous", base_confirmed: false, confirm_path: "/bekleyen-kayitlar",
              revenue_cents: 0, expense_cents: 0, other_currencies: [],
              currency_totals: [
                { currency: "?", revenue_cents: 9_000_000, expense_cents: 1_240_000, cash_in_cents: 0, cash_out_cents: 0, rows: 2 },
              ],
              possible_duplicates: 0,
              period: { start: "2026-03", end: "2026-03", months: 1, label: "x", is_default: true, available_start: "2026-03", available_end: "2026-03", available_months: 1, future_rows: 0, future_latest: null },
              months: [],
            },
          },
        });
      }
      return Promise.resolve({ data: { data: [] } });
    });
    wrap(<LedgerCard />);
    const totals = await screen.findByTestId("per-currency-totals");
    expect(totals.textContent).toMatch(/90\.000/);
    expect(totals.textContent).toContain("para birimi bilinmiyor");
    expect(totals.textContent).not.toMatch(/[$₺]|\?/);
  });
});
