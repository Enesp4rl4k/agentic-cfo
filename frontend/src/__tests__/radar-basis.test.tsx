/**
 * The radar says how well it knows what it shows: the opening balance has the day of its
 * statement and a warning when it is old; an estimated or assumed row carries a small tag with
 * its reason; a week says how much of it rests on estimates. The numbers are the server's.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);
vi.mock("next/link", async () => await import("./dashboard-mocks").then((m) => m.nextLinkModule));

import NakitRadariPage from "@/app/(dashboard)/nakit-radari/page";
import { ledgerSpies, noBasis, openingCashFixture, renderWithQuery } from "./dashboard-mocks";

const item = (over: Record<string, unknown>) => ({
  id: "i1",
  counterparty: "Mal Sahibi A.Ş.",
  description: null,
  amount_cents: 25_000_00,
  due_date: "2025-02-05",
  expected_date: "2025-02-05",
  delay_days: 0,
  is_overdue: false,
  instrument: "invoice",
  rescheduled: false,
  basis: "known",
  basis_reason: "document_due_date",
  basis_inputs: {},
  rules_verified: null,
  ...over,
});

const radar = (opening: Record<string, unknown>, payables: unknown[] = []) => ({
  anchor_date: "2025-02-01",
  starting_cash_cents: 80_000_00,
  starting_cash_as_of: opening.as_of,
  opening_cash: { ...openingCashFixture, balance_cents: 80_000_00, ...opening },
  weeks: [
    {
      week: 1,
      start_date: "2025-02-01",
      end_date: "2025-02-07",
      inflow_cents: 0,
      outflow_cents: payables.length ? 25_000_00 : 0,
      net_cents: 0,
      end_balance_cents: 80_000_00,
      receivables: [],
      payables,
      inflow_basis: noBasis,
      outflow_basis: payables.length ? { known_cents: 0, estimated_cents: 25_000_00, assumed_cents: 0 } : noBasis,
    },
  ],
  shortfall: null,
  overdue_receivables: [],
  overdue_payables_cents: 0,
  undated_receivables_cents: 0,
  undated_payables_cents: 0,
  beyond_horizon_cents: 0,
  other_currency_items: 0,
  not_included: [],
});

beforeEach(() => {
  ledgerSpies.getCashRadar.mockReset();
});

describe("Nakit Radarı: how well each figure is known", () => {
  it("warns that a 40-day-old balance is old, names its date and links to an upload", async () => {
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ as_of: "2024-12-23", age_days: 40, stale: true }));
    renderWithQuery(<NakitRadariPage />);
    expect(await screen.findByText("23 Aralık ekstresine göre kasa")).toBeTruthy();
    expect(screen.getByText("Bu bakiye 40 gün önceki ekstreye dayanıyor")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Yeni ekstre yükle" }).getAttribute("href")).toBe("/baglan");
    // The headline answer carries the caveat too, not only the card further down.
    expect(screen.getByText("Bu cevap 23 Aralık tarihli eski bir ekstre bakiyesine dayanıyor.")).toBeTruthy();
  });

  it("shows no warning for a fresh balance", async () => {
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ as_of: "2025-01-30", age_days: 2, stale: false }));
    renderWithQuery(<NakitRadariPage />);
    expect(await screen.findByText("30 Ocak ekstresine göre kasa")).toBeTruthy();
    expect(screen.queryByText(/gün önceki ekstreye dayanıyor/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Yeni ekstre yükle" })).toBeNull();
  });

  it("tags an estimated row with its reason, says how much of the week is estimated, and flags unverified tax rules", async () => {
    const tax = item({
      id: "t1",
      counterparty: "GİB / SGK",
      instrument: "tax",
      basis: "estimated",
      basis_reason: "tax_historical_median",
      basis_inputs: { payments_observed: 3, median_cents: 25_000_00, tax_type: "kdv" },
      rules_verified: false,
    });
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ as_of: "2025-01-30", age_days: 2 }, [tax]));
    renderWithQuery(<NakitRadariPage />);
    const tag = await screen.findByRole("button", { name: /Neden tahmini/ });
    expect(tag.textContent).toBe("tahmini");
    expect(tag.getAttribute("title")).toContain("Geçmiş 3 vergi/SGK ödemenizin ortancası");
    expect(tag.getAttribute("title")).toContain("doğrulanmadı");
    expect(screen.getAllByText(/tahmini.*25\.000/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Vergi ve SGK günleri henüz resmî takvimle doğrulanmadı/).length).toBeGreaterThan(0);
    fireEvent.click(tag);
    expect(tag.getAttribute("aria-expanded")).toBe("true");
  });

  it("puts no tag on a documented row", async () => {
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ as_of: "2025-01-30" }, [item({})]));
    renderWithQuery(<NakitRadariPage />);
    expect(await screen.findByText("Mal Sahibi A.Ş.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Neden tahmini/ })).toBeNull();
  });
});
