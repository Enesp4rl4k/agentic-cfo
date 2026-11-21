/**
 * Money is written in the currency the payload states, never the stored organisation default.
 *
 * `Organization.base_currency` is "USD" until an owner confirms one. These tests mock the organisation as
 * stored "USD", unconfirmed, with lira data: the P&L and cash-flow pages must say lira. A confirmed EUR
 * organisation must say euro. The mock is NOT what makes these pass: it says USD.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { orgBox, dashboardBox } = vi.hoisted(() => ({
  orgBox: { current: {} as Record<string, unknown> },
  dashboardBox: { current: {} as Record<string, unknown> },
}));

vi.mock("@/hooks/useOrgSettings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useOrgSettings")>();
  return {
    ...actual,
    useOrgSettings: () => ({ org: orgBox.current, loading: false, error: null, refresh: () => {}, locale: "tr-TR" }),
  };
});
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("job=j1") }));
vi.mock("@/hooks/useCFO", () => ({
  useDashboard: () => ({ data: dashboardBox.current, isLoading: false, error: null }),
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn().mockResolvedValue({ data: { data: null } }), post: vi.fn() } }));
vi.mock("@/components/held-rows/HeldRowsLink", () => ({ HeldRowsLink: () => null }));
vi.mock("recharts", () => {
  const Null = () => null;
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    Area: Null, AreaChart: Box, Bar: Null, BarChart: Box, CartesianGrid: Null, Cell: Null, ReferenceLine: Null,
    ResponsiveContainer: Box, Tooltip: Null, XAxis: Null, YAxis: Null,
  };
});

import PnLPage from "@/app/(dashboard)/pnl/page";
import CashflowPage from "@/app/(dashboard)/cashflow/page";

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

const pnl = (extra: Record<string, unknown>) => ({
  revenue: 500_000, cogs: 100_000, gross_profit: 400_000, gross_margin: 0.8, ebitda: 300_000, ebitda_margin: 0.6,
  net_income: 250_000, net_margin: 0.5, opex: { rent: 100_000 }, narrative: "", ...extra,
});
const cashflow = (extra: Record<string, unknown>) => ({
  operating: 500_000, investing: 0, financing: 0, net_change: 500_000, narrative: "", alerts: [],
  monthly_series: [{ month: "2026-03", in: 60_000_000, out: 10_000_000, net: 50_000_000 }], ...extra,
});

const storedUsdUnconfirmed = {
  org_id: "o", name: "T", locale: "tr-TR", base_currency: "USD", base_currency_confirmed: false,
  effective_currency: "TRY", base_state: "single_unconfirmed",
};

afterEach(() => vi.clearAllMocks());

describe("P&L and cash flow follow the payload's currency", () => {
  it("a stored-USD, unconfirmed company with lira data sees lira", () => {
    orgBox.current = storedUsdUnconfirmed;
    dashboardBox.current = {
      pnl: pnl({ currency: "TRY", base_state: "single_unconfirmed", other_currencies: [] }),
      cashflow: cashflow({ currency: "TRY", base_state: "single_unconfirmed", other_currencies: [] }),
    };
    const { container, unmount } = wrap(<PnLPage />);
    expect(container.textContent).toContain("₺500.000");
    expect(container.textContent).not.toContain("$");
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("henüz onaylanmadı");
    unmount();

    const cash = wrap(<CashflowPage />);
    expect(cash.container.textContent).toContain("₺500.000");
    expect(cash.container.textContent).not.toContain("$");
  });

  it("a confirmed euro company sees euro on both pages", () => {
    orgBox.current = { ...storedUsdUnconfirmed, base_currency: "EUR", base_currency_confirmed: true, effective_currency: "EUR", base_state: "confirmed" };
    dashboardBox.current = {
      pnl: pnl({ currency: "EUR", base_state: "confirmed", other_currencies: [] }),
      cashflow: cashflow({ currency: "EUR", base_state: "confirmed", other_currencies: [] }),
    };
    const pnlView = wrap(<PnLPage />);
    expect(pnlView.container.textContent).toContain("€500.000");
    expect(pnlView.container.textContent).not.toContain("$");
    pnlView.unmount();
    const cash = wrap(<CashflowPage />);
    expect(cash.container.textContent).toContain("€500.000");
  });

  it("several currencies and none confirmed: no single headline, each currency alone, the figures labelled", () => {
    orgBox.current = { ...storedUsdUnconfirmed, effective_currency: null, base_state: "ambiguous" };
    dashboardBox.current = {
      pnl: pnl({
        currency: "TRY", base_state: "ambiguous",
        other_currencies: [{ currency: "USD", revenue_cents: 9_000_000, expense_cents: 1_240_000, rows: 2 }],
      }),
      cashflow: cashflow({ currency: "TRY", base_state: "ambiguous", other_currencies: [{ currency: "USD", cash_in_cents: 5_000_000, cash_out_cents: 0, rows: 1 }] }),
    };
    const view = wrap(<PnLPage />);
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("Şirket para biriminizi seçin");
    const lines = screen.getByTestId("pnl-per-currency").textContent ?? "";
    expect(lines).toMatch(/TRY: /);
    expect(lines).toMatch(/USD: /);
    expect(lines).toMatch(/90\.000/);
    expect(screen.getByTestId("dominant-caption").textContent).toContain("yalnızca TRY");
    expect(view.container.textContent).toContain("₺500.000");                 // the labelled TRY figures
    expect(view.container.textContent).not.toContain("$500");
    view.unmount();

    const cash = wrap(<CashflowPage />);
    expect(screen.getByTestId("base-currency-notice").textContent).toContain("Şirket para biriminizi seçin");
    expect(screen.getByTestId("dominant-caption").textContent).toContain("yalnızca TRY");
    expect(cash.container.textContent).toMatch(/USD: /);
  });
});

import { renderHook } from "@testing-library/react";
import { CurrencyScope, useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { JournalLeftOutBanner } from "@/components/ui/other-currency-lines";
import { parseLeftOut } from "@/lib/api/muhasebe";

describe("useCurrencyFormat can no longer use the stored default", () => {
  it("with no argument it uses the effective currency, not the stored USD", () => {
    orgBox.current = storedUsdUnconfirmed;
    expect(renderHook(() => useCurrencyFormat()).result.current(1000)).toContain("₺");
  });

  it("with an unconfirmed org and no effective currency it writes the bare number", () => {
    orgBox.current = { org_id: "o", locale: "tr-TR", base_currency: "USD", base_currency_confirmed: false, effective_currency: null };
    expect(renderHook(() => useCurrencyFormat()).result.current(1000)).toBe("1.000");
  });

  it("an explicit currency and a scope win", () => {
    orgBox.current = storedUsdUnconfirmed;
    expect(renderHook(() => useCurrencyFormat("EUR")).result.current(1000)).toContain("€");
    const wrapper = ({ children }: { children: React.ReactNode }) => <CurrencyScope currency="GBP">{children}</CurrencyScope>;
    expect(renderHook(() => useCurrencyFormat(), { wrapper }).result.current(1000)).toContain("£");
  });
});

describe("a statutory export says what it left out", () => {
  it("parses the header and shows the banner", () => {
    expect(parseLeftOut("USD=3, EUR=1")).toEqual({ USD: 3, EUR: 1 });
    expect(parseLeftOut(undefined)).toEqual({});
    orgBox.current = storedUsdUnconfirmed;
    const { container } = render(<JournalLeftOutBanner left={{ USD: 3, EUR: 1 }} />);
    expect(container.textContent).toContain("4 dövizli kayıt bu dökümde yok");
    const none = render(<JournalLeftOutBanner left={{}} />);
    expect(none.container.textContent).toBe("");
  });
});
