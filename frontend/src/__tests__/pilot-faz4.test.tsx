import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getRadarBacktest = vi.fn();
const getDecisionSuccessMetrics = vi.fn();

vi.mock("@/lib/api/pilot", () => ({
  getRadarBacktest: (...args: unknown[]) => getRadarBacktest(...args),
  getDecisionSuccessMetrics: (...args: unknown[]) => getDecisionSuccessMetrics(...args),
}));

vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { accessToken: "fake-jwt", user: { name: "Admin" } },
    status: "authenticated",
  }),
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

import PilotAdminPage from "@/app/(dashboard)/pilot/page";

describe("Pilot Admin Page — Faz 4 Backtesting & Decision Metrics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/pilot/invites")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: [] }) });
      }
      if (url.includes("/pilot/feedback/summary")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: null }) });
      }
      if (url.includes("/pilot/feedback")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { entries: [] } }) });
      }
      if (url.includes("/pilot/status")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              data: {
                pilot_active: true,
                max_users: 50,
                current_users: 10,
                slots_remaining: 40,
                accepting_new_users: true,
              },
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: null }) });
    });
  });

  it("renders 4-week radar backtesting card with high accuracy tier", async () => {
    getRadarBacktest.mockResolvedValue({
      org_id: "org1",
      target_date: "2025-02-28",
      lookback_weeks: 4,
      projected_end_balance_cents: 100_000_00,
      actual_proven_balance_cents: 102_000_00,
      variance_cents: 2_000_00,
      variance_pct: 2.0,
      accuracy_tier: "HIGH",
      summary: "Radar tahmini fiili defter bakiyesinden %2.0 saptı (Yüksek doğruluk).",
    });

    getDecisionSuccessMetrics.mockResolvedValue({
      org_id: "org1",
      total_recommendations: 10,
      responded_count: 10,
      unresponded_count: 0,
      adopted_count: 8,
      deferred_count: 1,
      dismissed_count: 1,
      open_count: 0,
      closed_count: 10,
      adoption_rate_pct: 80.0,
      dismissal_rate_pct: 10.0,
      correction_rate_pct: 10.0,
      response_rate_pct: 100.0,
      accepted_expected_amount_cents: 250_000_00,
      total_impact_cents: 250_000_00,
      summary: "Toplam 10 agent önerisinden 8 tanesi uygulandı (%80.0 kabul).",
    });

    render(<PilotAdminPage />);

    await waitFor(() => {
      expect(screen.getByText("4 Haftalık Nakit Radarı Backtesti")).toBeInTheDocument();
      expect(screen.getByText("Karar Defteri ve Öneri Benimsenmesi")).toBeInTheDocument();
      expect(screen.getByText("80.0%")).toBeInTheDocument();
      expect(screen.getByText("10.0%")).toBeInTheDocument();
      expect(screen.getByText("Yüksek Doğruluk (≤ %10 sapma)")).toBeInTheDocument();
    });
  });
});
