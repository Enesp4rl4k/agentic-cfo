/**
 * The transactions page: Turkish through the i18n files, and every row in its OWN currency.
 *
 * It used to be hard-coded English, and a row with no currency of its own took the organisation's stored
 * `base_currency` (a column default of USD) or "TRY". A row now shows the currency it carries: a USD row
 * reads in dollars, a TRY row in lira, one that names none as a bare number.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { orgBox, dataBox } = vi.hoisted(() => ({
  orgBox: { current: {} as Record<string, unknown> },
  dataBox: { current: null as Record<string, unknown> | null },
}));

vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({ org: orgBox.current, loading: false, error: null, refresh: () => {}, locale: "tr-TR" }),
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("job=job-1") }));
vi.mock("@/hooks/useCFO", () => ({
  useTransactions: () => ({ data: dataBox.current, isLoading: false, error: null }),
  useCorrectCategory: () => ({ mutate: vi.fn(), isPending: false }),
}));

import TransactionsPage from "@/app/(dashboard)/transactions/page";

const tx = (id: string, cents: number, currency: string | null, type = "income") => ({
  id, job_id: "job-1", amount_cents: cents, currency, type, category: type === "income" ? "revenue" : "other_expense",
  description: `d-${id}`, vendor: null, transaction_date: "2026-01-10T00:00:00+00:00", confidence: 0.9,
});

const base = (state: string, currency: string | null, present: Record<string, number> = {}) => ({
  state, currency, confirmed: state === "confirmed", dominant: null, present, confirm_path: "/bekleyen-kayitlar",
});

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><TransactionsPage /></QueryClientProvider>);
};

const rowOf = (id: string) => screen.getByText(`d-${id}`).closest("tr") as HTMLElement;

// Stored USD (the column default), unconfirmed, Turkish locale: the stored value must not leak into the page.
const storedUsd = { org_id: "o", name: "T", locale: "tr-TR", base_currency: "USD", base_currency_confirmed: false };

afterEach(() => vi.clearAllMocks());

describe("transactions page: Turkish", () => {
  it("writes its headings, filters and column titles in Turkish", () => {
    orgBox.current = storedUsd;
    dataBox.current = { total: 1, limit: 2000, offset: 0, base: base("single_unconfirmed", "TRY", { TRY: 1 }), transactions: [tx("a", 100_000, "TRY")] };
    wrap();
    expect(screen.getByRole("heading", { name: "İşlemler" })).toBeTruthy();
    expect(screen.getByText(/1 işlem/)).toBeTruthy();
    for (const label of ["Tarih", "Açıklama", "Firma", "Kategori", "Tutar"]) {
      expect(screen.getByRole("button", { name: `${label} sütununa göre sırala` })).toBeTruthy();
    }
    expect(screen.getByLabelText("İşlemlerde ara")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Tüm türler" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "İşlemleri CSV olarak indir" })).toBeTruthy();
    // none of the English strings it used to hard-code
    for (const english of ["Transactions", "Total In", "Export CSV", "Search description or vendor…", "All categories"]) {
      expect(document.body.textContent).not.toContain(english);
    }
  });

  it("says in Turkish that there are no transactions", () => {
    orgBox.current = storedUsd;
    dataBox.current = null;
    wrap();
    expect(screen.getByText("Henüz işlem yok")).toBeTruthy();
    expect(screen.getByText("Belge yükle")).toBeTruthy();
  });
});

describe("transactions page: each row in its own currency", () => {
  it("shows a USD row in dollars and a TRY row in lira, under a stored-USD, unconfirmed company", () => {
    orgBox.current = storedUsd;
    dataBox.current = {
      total: 2, limit: 2000, offset: 0, base: base("ambiguous", null, { TRY: 1, USD: 1 }),
      transactions: [tx("try", 1_000_000, "TRY"), tx("usd", 2_500_000, "USD")],
    };
    wrap();
    expect(within(rowOf("try")).getByText(/₺/)).toBeTruthy();
    expect(rowOf("try").textContent).not.toContain("$");
    expect(rowOf("usd").textContent).toMatch(/\$/);
    expect(rowOf("usd").textContent).not.toContain("₺");
    expect(rowOf("usd").textContent).toMatch(/25\.000/);
  });

  it("with a confirmed base, other-currency rows keep their own symbol and are not in the totals", () => {
    orgBox.current = { ...storedUsd, base_currency: "TRY", base_currency_confirmed: true, effective_currency: "TRY" };
    dataBox.current = {
      total: 3, limit: 2000, offset: 0, base: base("confirmed", "TRY", { TRY: 2, EUR: 1 }),
      transactions: [tx("a", 1_000_000, "TRY"), tx("b", 500_000, "TRY", "expense"), tx("c", 900_000, "EUR")],
    };
    wrap();
    expect(screen.getByText("Toplam giriş").parentElement?.textContent).toMatch(/10\.000/);   // TRY only
    expect(screen.getByText("Net").parentElement?.textContent).toMatch(/5\.000/);
    expect(rowOf("c").textContent).toMatch(/€/);
    expect(rowOf("c").textContent).not.toContain("₺");
  });

  it("a row that names no currency is a bare number, never the stored default", () => {
    orgBox.current = storedUsd;
    dataBox.current = {
      total: 1, limit: 2000, offset: 0, base: base("single_unconfirmed", "TRY", { TRY: 1 }),
      transactions: [tx("none", 1_234_500, null)],
    };
    wrap();
    const text = rowOf("none").textContent ?? "";
    expect(text).toMatch(/12\.345/);
    expect(text).not.toMatch(/[$₺€]/);
  });

  it("an older payload without `base` does not fall back to the stored USD default", () => {
    orgBox.current = storedUsd;                       // stored USD, unconfirmed, no effective currency
    dataBox.current = { total: 1, limit: 2000, offset: 0, transactions: [tx("a", 100_000, "TRY")] };
    wrap();
    expect(screen.queryByText("Toplam giriş")).toBeNull();  // no single currency: no headline strip
    expect(rowOf("a").textContent).toMatch(/₺/);
    expect(document.body.textContent).not.toContain("$");
  });
});
