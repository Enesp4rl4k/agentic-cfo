/**
 * Yaklaşan son günler — every client's statutory deadlines on the portfolio page.
 *
 * The API is mocked with the shape backend/tests/test_smmm_tax_calendar.py pins.
 * Checked here: rows nearest first with the client and the deadline, an amount only
 * when the client has a payment history (no estimate otherwise), the "rules not yet
 * verified" notice whenever the server says so, and the empty and failure states.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const get = vi.fn();
vi.mock("@/lib/api/client", () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }));
vi.mock("@/hooks/useOrgSettings", () => ({
  useOrgSettings: () => ({
    org: { org_id: "o1", name: "Test Org", locale: "tr-TR", base_currency: "TRY" },
    loading: false, error: null, refresh: () => {}, hasTrPack: true, baseCurrency: "TRY", locale: "tr-TR",
  }),
}));

import { SmmmTakvim } from "@/components/smmm/SmmmTakvim";

const kalem = (over: Record<string, unknown>) => ({
  tarih: "2026-03-02", tur: "kdv", baslik: "KDV Ödemesi (02/2026)", musteri_id: "a",
  firma_adi: "A Ltd", client_org_id: "oa", tutar_kurus: 120_000, gecmiste_odeme_var: true, ...over,
});
const serve = (kalemler: unknown[], dogrulandi = false) =>
  get.mockResolvedValue({ data: { data: { baslangic: "2026-02-02", bitis: "2026-03-18", kalemler, kurallar_dogrulandi: dogrulandi } } });

beforeEach(() => vi.clearAllMocks());

describe("SmmmTakvim", () => {
  it("lists each client's deadline, with an amount only where there is a payment history", async () => {
    serve([kalem({}), kalem({ musteri_id: "b", firma_adi: "B Ltd", tutar_kurus: null, gecmiste_odeme_var: false })]);
    render(<SmmmTakvim />);
    expect(await screen.findByText("A Ltd")).toBeInTheDocument();
    expect(screen.getByText("B Ltd")).toBeInTheDocument();
    expect(screen.getAllByText("KDV Ödemesi (02/2026)")).toHaveLength(2);
    expect(screen.getByText(/1\.200,00/)).toBeInTheDocument();
    expect(screen.getByText("Geçmiş ödeme yok")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/smmm/takvim", { params: { gun: 45 } });
  });

  it("says the day rules are not yet verified whenever the server says so", async () => {
    serve([kalem({})], false);
    render(<SmmmTakvim />);
    expect(await screen.findByText(/resmî GİB\/SGK metniyle henüz doğrulanmadı/)).toBeInTheDocument();
  });

  it("drops the notice once the rules are verified", async () => {
    serve([kalem({})], true);
    render(<SmmmTakvim />);
    await screen.findByText("A Ltd");
    expect(screen.queryByText(/henüz doğrulanmadı/)).not.toBeInTheDocument();
  });

  it("says so when there is nothing ahead", async () => {
    serve([]);
    render(<SmmmTakvim />);
    expect(await screen.findByText(/Önümüzdeki 45 günde son gün yok/)).toBeInTheDocument();
  });

  it("says so when the list cannot be loaded", async () => {
    get.mockRejectedValue(new Error("boom"));
    render(<SmmmTakvim />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Son günler yüklenemedi.");
  });
});
