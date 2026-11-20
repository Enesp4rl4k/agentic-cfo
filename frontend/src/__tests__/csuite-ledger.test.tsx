import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getCHROMetrics = vi.fn();
const getCOOMetrics = vi.fn();
const getCTOMetrics = vi.fn();

vi.mock("@/lib/api/csuite", () => ({
  getCHROMetrics: (...args: unknown[]) => getCHROMetrics(...args),
  getCOOMetrics: (...args: unknown[]) => getCOOMetrics(...args),
  getCTOMetrics: (...args: unknown[]) => getCTOMetrics(...args),
}));

vi.mock("@/hooks/useOrgSettings", () => ({
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
}));

import { CSuiteLedgerCard } from "@/components/command-center/CSuiteLedgerCard";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("CSuiteLedgerCard — Ledger-Derived Executive Insights", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders CHRO, COO, and CTO metric panels when ledger data exists", async () => {
    getCHROMetrics.mockResolvedValue({
      org_id: "org1",
      revenue_cents: 1_000_000_00,
      payroll_cents: 350_000_00,
      payroll_ratio_pct: 35.0,
      monthly_trend: [],
      trend_direction: "stable",
      summary: "Son 6 ayda personel giderleri ortalama %35.0 seviyesinde.",
    });

    getCOOMetrics.mockResolvedValue({
      org_id: "org1",
      total_expense_cents: 800_000_00,
      top_suppliers: [{ supplier: "Tedarikci A", amount_cents: 400_000_00, share_pct: 50.0 }],
      top1_share_pct: 50.0,
      top3_share_pct: 75.0,
      top5_share_pct: 85.0,
      concentration_risk: "HIGH",
      summary: "En buyuk tedarikci toplam giderlerin %50.0 kadari.",
    });

    getCTOMetrics.mockResolvedValue({
      org_id: "org1",
      total_tech_spend_cents: 45_000_00,
      tech_share_pct: 5.6,
      monthly_trend: [],
      recurring_tech_vendors: [
        { vendor: "AWS", monthly_cents: 20_000_00, frequency_months: 6 },
        { vendor: "GitHub", monthly_cents: 5_000_00, frequency_months: 6 },
      ],
      summary: "Bulut ve SaaS harcamalari %5.6 pay aliyor.",
    });

    renderWithClient(<CSuiteLedgerCard />);

    expect(await screen.findByText("C-Suite Defter Zekası")).toBeInTheDocument();
    expect(screen.getByText("CHRO · Personel ve Bordro")).toBeInTheDocument();
    expect(screen.getByText("35.0%")).toBeInTheDocument();
    expect(screen.getByText("COO · Tedarikçi Yoğunlaşması")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("CTO · Bulut ve Yazılım Ayak İzi")).toBeInTheDocument();
    expect(screen.getByText("5.6%")).toBeInTheDocument();
  });
});
