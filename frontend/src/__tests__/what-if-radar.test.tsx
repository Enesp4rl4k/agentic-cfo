/**
 * What-If Radar Panel (Plan v12 Faz 3) Vitest Test
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WhatIfRadarPanel } from "@/components/simulation/WhatIfRadarPanel";
import { tr } from "@/lib/i18n/messages/tr";

const simulateWhatIfMock = vi.fn();

vi.mock("@/lib/api/simulation", () => ({
  simulateWhatIf: (...args: unknown[]) => simulateWhatIfMock(...args),
}));

vi.mock("@/hooks/useCurrencyFormat", () => ({
  useCurrencyFormat: () => (val: number) => `₺${val.toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`,
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

describe("WhatIfRadarPanel", () => {
  it("renders scenario controls when toggle button is clicked", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <WhatIfRadarPanel copy={tr.cashRadar} fmt={(v) => `₺${v}`} />
      </QueryClientProvider>
    );

    expect(screen.getByText("What-If Senaryo Simülatörü")).toBeDefined();

    // Senaryo Düzenle butonuna bas
    const toggleBtn = screen.getByText("Senaryo Düzenle");
    fireEvent.click(toggleBtn);

    // Kontroller görünmeli
    expect(screen.getByText("Yeni Personel Alımı (kişi)")).toBeDefined();
    expect(screen.getByText("Ciro Değişimi (%)")).toBeDefined();
    expect(screen.getByText("Senaryoyu Simüle Et")).toBeDefined();
  });

  it("calls simulateWhatIf API and renders simulation results", async () => {
    simulateWhatIfMock.mockResolvedValueOnce({
      starting_cash_cents: 10000000,
      simulated: {
        iterations: 5000,
        cash_deficit_probability_pct: 18.5,
        var_95_cents: -2500000,
        expected_lowest_balance_cents: 1200000,
        weeks: [
          {
            week: 1,
            baseline_cents: 10000000,
            p10_cents: 8000000,
            p50_cents: 10000000,
            p90_cents: 12000000,
            deficit_prob_pct: 0.0,
          },
        ],
        insights: ["3 yeni çalışan alımı nakit akışını etkiledi."],
      },
      scenarios: [],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <WhatIfRadarPanel copy={tr.cashRadar} fmt={(v) => `₺${v}`} />
      </QueryClientProvider>
    );

    const toggleBtn = screen.getByText("Senaryo Düzenle");
    fireEvent.click(toggleBtn);

    const simBtn = screen.getByText("Senaryoyu Simüle Et");
    fireEvent.click(simBtn);

    await waitFor(() => {
      expect(screen.getByText("%18.5")).toBeDefined();
      expect(screen.getByText("3 yeni çalışan alımı nakit akışını etkiledi.")).toBeDefined();
    });
  });
});
