/**
 * Amounts in different currencies are never added: the headline is the base currency and every
 * other currency is its own "not converted" line (backend app/core/currency_totals.py).
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { client, transactions } = vi.hoisted(() => ({
  client: { get: vi.fn(), post: vi.fn() },
  transactions: {
    current: [] as Record<string, unknown>[],
    base: { state: "confirmed", currency: "TRY" as string | null, confirmed: true, dominant: null as string | null, present: {} as Record<string, number>, confirm_path: "/bekleyen-kayitlar" },
  },
}));

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
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("job=job-1"),
}));
vi.mock("@/hooks/useCFO", () => ({
  useTransactions: () => ({
    data: { total: transactions.current.length, limit: 100, offset: 0, base: transactions.base, transactions: transactions.current },
    isLoading: false,
    error: null,
  }),
  useCorrectCategory: () => ({ mutate: vi.fn(), isPending: false }),
}));

import TransactionsPage from "@/app/(dashboard)/transactions/page";
import { LedgerCard } from "@/components/command-center/LedgerCard";
import { OtherCurrencyLines } from "@/components/ui/other-currency-lines";

const tx = (id: string, type: string, cents: number, currency: string) => ({
  id, job_id: "job-1", amount_cents: cents, currency, type,
  category: type === "income" ? "revenue" : "other_expense", description: `d-${id}`, vendor: null,
  transaction_date: "2026-01-10T00:00:00+00:00", confidence: 0.9,
});

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

afterEach(() => vi.clearAllMocks());

describe("transactions page totals", () => {
  it("shows the base total and the other currency on its own line, never added together", () => {
    transactions.current = [
      tx("a", "income", 100_000_00, "TRY"),
      tx("b", "expense", 30_000_00, "TRY"),
      tx("c", "income", 5_000_00, "USD"),
      tx("d", "expense", 1_240_000, "USD"),
    ];
    wrap(<TransactionsPage />);

    expect(screen.getByText("Total In").parentElement?.textContent).toMatch(/100\.000/);   // TRY only
    expect(screen.getByText("Total Out").parentElement?.textContent).toMatch(/30\.000/);
    expect(screen.getByText("Net").parentElement?.textContent).toMatch(/70\.000/);
    expect(document.body.textContent).not.toMatch(/105\.000/);                            // no 100k + 5k
    const lines = screen.getByTestId("other-currency-lines");
    expect(within(lines).getByText(/\$/)).toBeTruthy();                        // dollars, as dollars
    expect(lines.textContent).toMatch(/12\.400/);                              // the 12.400 USD out
    expect(lines.textContent).toMatch(/TRY/);                                  // "not converted to TRY"
  });

  it("without a confirmed currency and one currency present, headlines it and asks to confirm", () => {
    transactions.base = { state: "single_unconfirmed", currency: "TRY", confirmed: false, dominant: null, present: { TRY: 2 }, confirm_path: "/bekleyen-kayitlar" };
    transactions.current = [tx("a", "income", 100_000_00, "TRY"), tx("b", "expense", 30_000_00, "TRY")];
    wrap(<TransactionsPage />);
    expect(screen.getByText("Total In").parentElement?.textContent).toMatch(/100\.000/);
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("henüz onaylanmadı");
    expect(screen.getByText("Para birimini onayla").closest("a")?.getAttribute("href")).toBe("/bekleyen-kayitlar");
    transactions.base = { state: "confirmed", currency: "TRY", confirmed: true, dominant: null, present: {}, confirm_path: "/bekleyen-kayitlar" };
  });

  it("with several currencies and none confirmed shows no single total, each currency on its own, and every row", () => {
    transactions.base = { state: "ambiguous", currency: null, confirmed: false, dominant: "TRY", present: { TRY: 1, USD: 1 }, confirm_path: "/bekleyen-kayitlar" };
    transactions.current = [tx("a", "income", 100_000_00, "TRY"), tx("c", "income", 5_000_00, "USD")];
    wrap(<TransactionsPage />);
    expect(screen.queryByText("Total In")).toBeNull();
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("Şirket para biriminizi seçin");
    expect(screen.getByTestId("other-currency-lines").textContent).toMatch(/100\.000/);
    expect(screen.getByTestId("other-currency-lines").textContent).toMatch(/5\.000/);
    expect(screen.getByText("d-a")).toBeTruthy();
    expect(screen.getByText("d-c")).toBeTruthy();
    transactions.base = { state: "confirmed", currency: "TRY", confirmed: true, dominant: null, present: {}, confirm_path: "/bekleyen-kayitlar" };
  });

  it("has no extra line when every row is in the base currency", () => {
    transactions.current = [tx("a", "income", 100_000_00, "TRY")];
    wrap(<TransactionsPage />);
    expect(screen.queryByTestId("other-currency-lines")).toBeNull();
  });
});

describe("OtherCurrencyLines", () => {
  it("says what was left out, in both kinds of figure, and that ratios are base-only", () => {
    const { container } = wrap(
      <OtherCurrencyLines
        base="TRY"
        ratios
        items={[{ currency: "USD", revenue_cents: 0, expense_cents: 1_240_000, assumed_rows: 2 }]}
      />,
    );
    expect(container.textContent).toContain("çevrilmedi");
    expect(container.textContent).toMatch(/12\.400/);
    expect(container.textContent).toContain("2 tanesinin para birimi varsayıldı");
    expect(container.textContent).toContain("yalnızca TRY");
  });

  it("renders nothing for an empty list", () => {
    const { container } = wrap(<OtherCurrencyLines base="TRY" items={[]} />);
    expect(container.textContent).toBe("");
  });
});

describe("ledger card", () => {
  it("lists the foreign currencies beside the base totals", async () => {
    client.get.mockImplementation((url: string) => {
      if (url === "/ledger/summary") {
        return Promise.resolve({
          data: {
            data: {
              last_upload: null,
              open_items: { receivable_cents: 0, payable_cents: 0, no_due_date: 0, other_currency: 0 },
              rows: 6, currency: "TRY", base_state: "confirmed", base_confirmed: true, confirm_path: "/bekleyen-kayitlar",
              revenue_cents: 140_000_00, expense_cents: 30_000_00,
              other_currencies: [{ currency: "USD", revenue_cents: 0, expense_cents: 1_240_000, cash_in_cents: 0, cash_out_cents: 1_240_000, rows: 1 }],
              currency_totals: [],
              possible_duplicates: 0,
              period: { start: "2026-01", end: "2026-02", months: 2, label: "x", is_default: true, available_start: "2026-01", available_end: "2026-02", available_months: 2, future_rows: 0, future_latest: null },
              months: [],
            },
          },
        });
      }
      return Promise.resolve({ data: { data: [] } });
    });
    wrap(<LedgerCard />);
    const lines = await screen.findByTestId("other-currency-lines");
    expect(lines.textContent).toMatch(/12\.400/);
    expect(lines.textContent).toContain("çevrilmedi");
    expect(screen.getByText(/140\.000/)).toBeTruthy();
  });
});

describe("ledger card without a single headline", () => {
  it("shows every currency side by side and asks for the company currency", async () => {
    client.get.mockImplementation((url: string) => {
      if (url === "/ledger/summary") {
        return Promise.resolve({
          data: {
            data: {
              last_upload: null,
              open_items: { receivable_cents: 0, payable_cents: 0, no_due_date: 0, other_currency: 0 },
              rows: 5, currency: null, base_state: "ambiguous", base_confirmed: false, confirm_path: "/bekleyen-kayitlar",
              revenue_cents: 0, expense_cents: 0, other_currencies: [],
              currency_totals: [
                { currency: "TRY", revenue_cents: 900_000, expense_cents: 120_000, cash_in_cents: 0, cash_out_cents: 0, rows: 3 },
                { currency: "USD", revenue_cents: 9_000_000, expense_cents: 1_240_000, cash_in_cents: 0, cash_out_cents: 0, rows: 2 },
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
    expect(totals.textContent).toMatch(/9\.000/);
    expect(totals.textContent).toMatch(/90\.000/);
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("Şirket para biriminizi seçin");
  });
});
