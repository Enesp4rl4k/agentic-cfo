/**
 * The forecast scorecard speaks only from a saved forecast and a proven balance.
 * With numbers it shows projected, actual, the gap and the backend's tier; without them it names
 * what is missing and shows no figure; when it cannot load it says so.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getRadarBacktest = vi.fn();
vi.mock("@/lib/api/pilot", () => ({ getRadarBacktest: (...a: unknown[]) => getRadarBacktest(...a) }));

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

import { ForecastScorecard } from "@/components/radar/ForecastScorecard";

const base = {
  org_id: "org1",
  target_date: "2026-11-09",
  lookback_weeks: 4,
  projected_end_balance_cents: 640_000_00,
  actual_proven_balance_cents: 612_400_00,
  actual_proven_balance_as_of: "2026-11-09",
  variance_cents: -27_600_00,
  variance_pct: -4.3,
  accuracy_tier: "HIGH" as const,
  summary: "x",
};

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ForecastScorecard />
    </QueryClientProvider>,
  );
}

// Braces: a function returned from beforeEach is run as its teardown.
beforeEach(() => {
  getRadarBacktest.mockReset();
});

describe("ForecastScorecard", () => {
  it("shows projected, actual, the gap and the backend's tier", async () => {
    getRadarBacktest.mockResolvedValue(base);
    show();
    expect(await screen.findByText("Yüksek Doğruluk (≤ %10 sapma)")).toBeInTheDocument();
    expect(screen.getByText(/640\.000/)).toBeInTheDocument();
    expect(screen.getByText(/612\.400/)).toBeInTheDocument();
    expect(screen.getByText(/27\.600/)).toBeInTheDocument();
    expect(screen.getByText(/4,3/)).toBeInTheDocument();
  });

  it("names the missing forecast instead of inventing a gap", async () => {
    getRadarBacktest.mockResolvedValue({
      ...base,
      projected_end_balance_cents: null,
      variance_cents: null,
      variance_pct: null,
      accuracy_tier: "NO_FORECAST_SNAPSHOT",
      summary: "Bu tarih için saklanmış tahmin yok.",
    });
    show();
    expect(await screen.findByText("Tahmin Kaydı Yok")).toBeInTheDocument();
    expect(screen.getByText("Bu tarih için saklanmış tahmin yok.")).toBeInTheDocument();
    expect(screen.queryByText("Tahmin Edilen Bakiye")).toBeNull();
  });

  it("says when the scorecard could not be read", async () => {
    getRadarBacktest.mockRejectedValue(new Error("down"));
    show();
    expect(await screen.findByText("Tahmin karnesi okunamadı.")).toBeInTheDocument();
  });
});
