/**
 * Nakit Radarı: what a person sees from the 13-week radar.
 *
 * The API is mocked with the shape backend/tests/test_cash_radar.py pins. This
 * checks the page's side of the contract: a balance is shown only when the
 * statement proved one, a gap names its week and what could be done, and what
 * the radar did not count is said beside it.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const getCashRadar = vi.fn();
const getMondayBriefing = vi.fn().mockResolvedValue(null);
const respondToMondayBriefing = vi.fn().mockResolvedValue({ decision_id: "dec1", chosen_option_label: "Yaptım" });

vi.mock("@/lib/api/ledger", () => ({
  getCashRadar: (...args: unknown[]) => getCashRadar(...args),
  getMondayBriefing: (...args: unknown[]) => getMondayBriefing(...args),
  respondToMondayBriefing: (...args: unknown[]) => respondToMondayBriefing(...args),
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

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href, ...rest }, children),
}));

import NakitRadariPage from "@/app/(dashboard)/nakit-radari/page";
import { noBasis, openingCashFixture } from "./dashboard-mocks";

const week = (n: number, over: Record<string, unknown> = {}) => ({
  week: n,
  start_date: `2025-01-${String(1 + 7 * (n - 1)).padStart(2, "0")}`,
  end_date: `2025-01-${String(7 * n).padStart(2, "0")}`,
  inflow_cents: 0,
  outflow_cents: 0,
  net_cents: 0,
  end_balance_cents: 0,
  receivables: [],
  payables: [],
  inflow_basis: noBasis,
  outflow_basis: noBasis,
  ...over,
});

const radar = (over: Record<string, unknown> = {}) => ({
  anchor_date: "2025-01-01",
  starting_cash_cents: 100_000_00,
  starting_cash_as_of: "2025-01-01",
  opening_cash: openingCashFixture,
  weeks: [
    week(1, { end_balance_cents: 100_000_00 }),
    week(2, { inflow_cents: 50_000_00, net_cents: 50_000_00, end_balance_cents: 150_000_00 }),
    week(3, { outflow_cents: 30_000_00, net_cents: -30_000_00, end_balance_cents: 120_000_00 }),
  ],
  shortfall: null,
  overdue_receivables: [],
  overdue_payables_cents: 0,
  undated_receivables_cents: 0,
  undated_payables_cents: 0,
  beyond_horizon_cents: 0,
  other_currency_items: 0,
  not_included: ["Kira, maaş gibi düzenli ödemeler", "Vergi ve SGK yükümlülükleri", "Çek ve senetler"],
  ...over,
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NakitRadariPage />
    </QueryClientProvider>,
  );
}

// Braces: a function returned from beforeEach is run as its teardown.
beforeEach(() => {
  getCashRadar.mockReset();
});

describe("Nakit Radarı", () => {
  it("shows the proven balance with the day of its statement", async () => {
    getCashRadar.mockResolvedValue(radar());
    show();
    expect(await screen.findByText("Başlangıç nakdi")).toBeTruthy();
    expect(screen.getByText("1 Ocak ekstresine göre kasa")).toBeTruthy();
    expect(screen.getByText("Bakiye")).toBeTruthy();
    expect(screen.queryByText("Banka bakiyesi bilinmiyor")).toBeNull();
  });

  it("says the balance is unknown, and shows movement instead of a balance", async () => {
    getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    show();
    expect(await screen.findByText("Banka bakiyesi bilinmiyor")).toBeTruthy();
    expect(screen.getByText("Birikmiş hareket")).toBeTruthy();
    expect(screen.queryByText("Bakiye")).toBeNull();
    expect(screen.queryByText("Nakit açığı")).toBeNull();
  });

  it("names the week of a gap, its cause and the actions", async () => {
    getCashRadar.mockResolvedValue(radar({
      weeks: [week(1), week(2), week(3, { outflow_cents: 120_000_00, end_balance_cents: -70_000_00 })],
      shortfall: {
        week: 3, week_start: "2025-01-15", week_end: "2025-01-21", shortfall_cents: 70_000_00,
        driver: "3. haftada Ana Tedarikci AS 1.200,00 ödemesi bakiyeyi eksiye düşürüyor.",
        actions: [
          { type: "early_collection", title: "Tahsilatı öne çek: Sadik Musteri", detail: "Alacak bekleniyor.", amount_cents: 20_000_00 },
          { type: "financing", title: "Finansman ihtiyacı: ₺70.000,00", detail: "Açık 3. haftada başlıyor.", amount_cents: 70_000_00 },
        ],
      },
    }));
    show();
    expect(await screen.findByText("Nakit açığı")).toBeTruthy();
    expect(screen.getByText(/Ana Tedarikci AS/)).toBeTruthy();
    expect(screen.getByText("Tahsilatı öne çek: Sadik Musteri")).toBeTruthy();
    expect(screen.getByText("Finansman ihtiyacı: ₺70.000,00")).toBeTruthy();
  });

  it("lists what the radar does not count", async () => {
    getCashRadar.mockResolvedValue(radar({
      undated_receivables_cents: 25_000_00,
      overdue_receivables: [{ id: "r1", counterparty: "Eski Musteri", amount_cents: 40_000_00, expected_date: "2024-12-15" }],
      beyond_horizon_cents: 9_000_00,
      other_currency_items: 2,
    }));
    show();
    expect(await screen.findByText("Radara dahil değil")).toBeTruthy();
    expect(screen.getByText("Vergi ve SGK yükümlülükleri")).toBeTruthy();
    expect(screen.getByText("Vadesi olmayan alacak")).toBeTruthy();
    expect(screen.getByText(/Eski Musteri/)).toBeTruthy();
    expect(screen.getByText("13 hafta sonrası")).toBeTruthy();
    expect(screen.getByText("Başka para birimli kalem")).toBeTruthy();
  });

  it("puts the two queues that wait for a person in one block, each with its own link", async () => {
    getCashRadar.mockResolvedValue(radar({
      not_included: [
        "Kira, maaş gibi düzenli ödemeler",
        "3 kayıt incelemenizi bekliyor",
        "Karar bekleyen 1 belge (₺1.000,00 ödeme): mükerrer olabilir, siz karar verene kadar radarda yok",
      ],
      awaiting_decision: {
        rows: { count: 3, text: "3 kayıt incelemenizi bekliyor", path: "/bekleyen-kayitlar" },
        documents: {
          count: 1,
          text: "Karar bekleyen 1 belge (₺1.000,00 ödeme): mükerrer olabilir, siz karar verene kadar radarda yok",
          path: "/onay",
        },
      },
    }));
    show();
    expect(await screen.findByText("Kararınızı bekleyenler")).toBeTruthy();
    expect(screen.getByText("İncelenmesi gereken kayıtlar:")).toBeTruthy();
    expect(screen.getByText("Mükerrer olabilecek belgeler:")).toBeTruthy();
    const links = screen.getAllByRole("link", { name: "Karar ver" });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/bekleyen-kayitlar", "/onay"]);
    // each sentence is said once: in the block, not again in the plain list
    expect(screen.getAllByText(/3 kayıt incelemenizi bekliyor/).length).toBe(1);
    expect(screen.getAllByText(/Karar bekleyen 1 belge/).length).toBe(1);
    expect(screen.getByText("Kira, maaş gibi düzenli ödemeler")).toBeTruthy();
  });

  it("shows no block when nothing waits", async () => {
    getCashRadar.mockResolvedValue(radar({ awaiting_decision: null }));
    show();
    await screen.findByText("Radara dahil değil");
    expect(screen.queryByText("Kararınızı bekleyenler")).toBeNull();
  });

  it("points an empty company at its documents", async () => {
    getCashRadar.mockResolvedValue(radar({
      starting_cash_cents: null, starting_cash_as_of: null,
      weeks: [week(1), week(2), week(3)],
    }));
    show();
    const link = await screen.findByRole("link", { name: "Verilerimi bağla" });
    expect(link.getAttribute("href")).toBe("/baglan");
  });

  it("says so when the radar cannot be read", async () => {
    getCashRadar.mockRejectedValue(new Error("boom"));
    show();
    expect(await screen.findByText("Nakit radarı yüklenemedi.")).toBeTruthy();
  });

  it("renders the logbook (Seyir Defteri) when available", async () => {
    getCashRadar.mockResolvedValue(radar());
    getMondayBriefing.mockResolvedValue({
      briefing_id: "brief_123",
      org_id: "org1",
      full_text: "Bu hafta net nakit pozisyonunuzda 50.000 TL net giriş beklenmektedir.",
      action_title: "Tahsilat Takibi",
      action_detail: "Demir Çelik A.Ş. ödemesi",
      action_amount_cents: 50000_00,
      verified: true,
      fallback_used: false,
      week_start: "2025-02-03",
      fingerprint: "fp-radar",
    });
    show();
    expect(await screen.findByText("Seyir Defteri")).toBeTruthy();
    expect(screen.getByText("Defterle Doğrulandı")).toBeTruthy();
    expect(screen.getByText(/Bu hafta net nakit pozisyonunuzda/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yaptım" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ertele" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Gerek Yok" })).toBeTruthy();
  });

  it("answers the briefing it shows, fingerprint and all", async () => {
    // A second, hand-written client here sent no fingerprint after the backend
    // began to require one, and every answer from this page was refused (422).
    getCashRadar.mockResolvedValue(radar());
    getMondayBriefing.mockResolvedValue({
      briefing_id: "brief_123", org_id: "org1", full_text: "Metin.", action_title: "Tahsilat Takibi",
      action_detail: "", action_amount_cents: 0, verified: true, fallback_used: false,
      week_start: "2025-02-03", fingerprint: "fp-radar",
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Yaptım" }));
    await waitFor(() =>
      expect(respondToMondayBriefing).toHaveBeenCalledWith("done", "2025-02-03", "fp-radar"),
    );
  });
});
