/**
 * The forecast page's runway note carries the upload prompt AND a link to /upload when the balance is old;
 * a runway under a month is said as that (never "0 ay", which reads like an unknown).
 */
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render as rtlRender, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { box } = vi.hoisted(() => ({ box: { current: {} as Record<string, unknown> } }));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("job=j1") }));
vi.mock("@/hooks/useCFO", () => ({ useDashboard: () => ({ data: box.current, isLoading: false, error: null }) }));
vi.mock("@/hooks/useCurrencyFormat", () => ({
  useCurrencyFormat: () => (n: number) => String(n),
  useCurrencySymbol: () => "₺",
}));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o", name: "T", locale: "tr-TR", base_currency: "TRY" }, loading: false, error: null,
    refresh: () => {}, hasTrPack: true, focusMode: false, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));
vi.mock("recharts", () => {
  const Null = () => null;
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ComposedChart: Box, Area: Null, Line: Null, Bar: Null, XAxis: Null, YAxis: Null, CartesianGrid: Null,
    Tooltip: Null, ResponsiveContainer: Box, Legend: Null, ReferenceLine: Null,
  };
});

const render = (ui: React.ReactElement) =>
  rtlRender(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

import ForecastPage from "@/app/(dashboard)/forecast/page";

const dashboard = (runway: Record<string, unknown>, months: number | null) => ({
  alerts: [],
  forecast: {
    narrative: "",
    scenarios: { base: { label: "Base", description: "", runway_months: months, twelve_month_net: -1000, months: [] } },
    runway: { status: "computed", message: "Mesaj", months_needed: 3, months_used: 3, beyond_horizon: false, ...runway },
  },
});

describe("forecast runway note", () => {
  it("links to /upload when the balance is old", () => {
    box.current = dashboard({ stale: true, runway_months: 1.5, level: "warning" }, 1.5);
    render(<ForecastPage />);
    expect(screen.getByTestId("forecast-runway-upload").getAttribute("href")).toBe("/upload");
  });

  it("has no upload link when the balance is current, and says under a month as that", () => {
    box.current = dashboard({ stale: false, runway_months: 0, level: "critical" }, 0);
    render(<ForecastPage />);
    expect(screen.queryByTestId("forecast-runway-upload")).toBeNull();
    expect(screen.getAllByText("1 aydan az").length).toBeGreaterThan(0);
  });
});
