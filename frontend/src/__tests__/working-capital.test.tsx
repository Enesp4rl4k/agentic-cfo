/**
 * Nakit döngüsü — the page shows what was computed, with its formula, and
 * leaves a metric empty when an input is missing. It used to draw constants
 * against a sector average nothing measured.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api } = vi.hoisted(() => ({ api: { analyzeWorkingCapital: vi.fn() } }));
vi.mock("@/lib/api/analytics", () => api);

import WorkingCapitalPage from "@/app/(dashboard)/analytics/working-capital/page";

const metrik = (ad: string, gun: number | null) => ({
  ad, gun, formul: `${ad} formülü`, aciklama: `${ad} açıklaması`,
});

const sonuc = (over: Record<string, unknown> = {}) => ({
  metrikler: {
    dso: metrik("DSO", 60), dpo: metrik("DPO", 45),
    dio: metrik("DIO", 0), ccc: metrik("CCC", 15),
  },
  yorum: "Nakit döngünüz 15 gün.",
  eksik_girdiler: [],
  olcum: "hesaplandi",
  sektor_karsilastirmasi: null,
  sektor_karsilastirmasi_notu: "DSO/DPO için sektör ortalaması verimiz yok; karşılaştırma gösterilmiyor.",
  ...over,
});

async function hesapla() {
  fireEvent.change(screen.getByLabelText(/Alacaklar/), { target: { value: "60000" } });
  fireEvent.change(screen.getByLabelText("Yıllık ciro"), { target: { value: "365000" } });
  fireEvent.click(screen.getByRole("button", { name: "Hesapla" }));
}

describe("Nakit Döngüsü", () => {
  // A block body, not an expression: an arrow returning the mock hands vitest
  // the mock itself as beforeEach's teardown, and it calls it between tests.
  beforeEach(() => { api.analyzeWorkingCapital.mockReset(); });

  it("sends the figures that were typed", async () => {
    api.analyzeWorkingCapital.mockResolvedValue(sonuc());
    render(<WorkingCapitalPage />);
    await hesapla();
    await waitFor(() => expect(api.analyzeWorkingCapital).toHaveBeenCalledWith(
      expect.objectContaining({ accounts_receivable_try: 60000, annual_revenue_try: 365000 }),
    ));
  });

  it("shows each metric with the formula it came from", async () => {
    api.analyzeWorkingCapital.mockResolvedValue(sonuc());
    render(<WorkingCapitalPage />);
    await hesapla();
    expect(await screen.findByText("60.0 gün")).toBeInTheDocument();
    expect(screen.getByText("DSO formülü")).toBeInTheDocument();
    expect(screen.getByText(/sektör ortalaması verimiz yok/)).toBeInTheDocument();
  });

  it("leaves a metric empty and names the missing input", async () => {
    api.analyzeWorkingCapital.mockResolvedValue(sonuc({
      metrikler: {
        dso: metrik("DSO", null), dpo: metrik("DPO", 45),
        dio: metrik("DIO", 0), ccc: metrik("CCC", null),
      },
      eksik_girdiler: ["yıllık ciro"],
      yorum: "Döngü hesaplanamadı: yıllık ciro gerekli.",
    }));
    render(<WorkingCapitalPage />);
    await hesapla();
    expect(await screen.findByText("Eksik rakam var")).toBeInTheDocument();
    expect(screen.getByText(/yıllık ciro girilmeden/)).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBe(2);
  });

  it("says so when the request fails", async () => {
    api.analyzeWorkingCapital.mockImplementation(async () => { throw new Error("Sunucu hatası"); });
    render(<WorkingCapitalPage />);
    await hesapla();
    expect(await screen.findByText("Sunucu hatası")).toBeInTheDocument();
  });
});
