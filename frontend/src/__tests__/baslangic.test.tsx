/**
 * Başlangıç — the steps come from the organisation's data, and each state says
 * what to do next. The old guide was a slideshow whose progress lived in the
 * browser, so none of this could be asserted.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api, cfo, packet } = vi.hoisted(() => ({
  api: { baslangicDurumu: vi.fn(), firmaOlustur: vi.fn() },
  cfo: { approveJob: vi.fn() },
  packet: { getDecisionPacket: vi.fn() },
}));
vi.mock("@/lib/api/baslangic", () => api);
vi.mock("@/lib/api/cfo", () => cfo);
vi.mock("@/lib/api/decisionPacket", () => packet);
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href }, children),
}));

import BaslangicPage from "@/app/(dashboard)/baslangic/page";

const durum = (over: Record<string, unknown> = {}) => ({
  firma: { var: true, ad: "Kobi A.Ş." },
  veri: { analiz_sayisi: 1, parasut_bagli: false },
  son_analiz: null,
  tamamlanan_analiz: 0,
  otomatik: { eposta: false, parasut_otomatik: false },
  ...over,
});

describe("Başlangıç", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    cfo.approveJob.mockReset();
    // The packet is optional furniture: reject so the panel renders nothing
    // and the assertions below stay about the approval flow itself.
    packet.getDecisionPacket.mockReset();
    packet.getDecisionPacket.mockRejectedValue(new Error("no packet"));
  });

  it("counts the steps the organisation has actually finished", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 2 }));
    render(<BaslangicPage />);
    expect(await screen.findByText("Kurulum tamam")).toBeInTheDocument();
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Komuta Merkezi/ })).toHaveAttribute("href", "/command-center");
  });

  it("asks for a company name when there is none, and creates it", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ firma: { var: false, ad: null }, veri: { analiz_sayisi: 0, parasut_bagli: false } }));
    api.firmaOlustur.mockResolvedValue(undefined);
    render(<BaslangicPage />);
    expect(await screen.findByText("3 adımdan 0'i tamam")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Firma adı"), { target: { value: "Yıldız Tekstil" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(api.firmaOlustur).toHaveBeenCalledWith("Yıldız Tekstil"));
  });

  it("says an analysis is waiting for approval, with the confidence and the threshold", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-1", durum: "awaiting_review", onay_bekliyor: true, guven: 0.62,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
    }));
    render(<BaslangicPage />);
    expect(await screen.findByText(/güveni %62/)).toBeInTheDocument();
    expect(screen.getByText(/Eşik %80/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Önce sonuçlara bakayım/ })).toHaveAttribute("href", "/pnl?job=job-1");
  });

  it("approves only after the confirmation is accepted", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-1", durum: "awaiting_review", onay_bekliyor: true, guven: 0.62,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
    }));
    cfo.approveJob.mockResolvedValue(undefined);
    render(<BaslangicPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Onayla ve tamamla" }));
    expect(await screen.findByText("Analizi onaylıyor musunuz?")).toBeInTheDocument();
    expect(cfo.approveJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(cfo.approveJob).toHaveBeenCalledWith("job-1"));
  });

  it("shows a failed analysis with its reason and a way to retry", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-2", durum: "failed", onay_bekliyor: false, guven: null,
                    dosya: "ekstre.csv", hata: "Tarih sütunu bulunamadı.", olusturma: null },
    }));
    render(<BaslangicPage />);
    expect(await screen.findByText("Tarih sütunu bulunamadı.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dosyayı yeniden bağla/ })).toHaveAttribute("href", "/baglan");
  });

  it("says so when the status cannot be read, instead of an empty page", async () => {
    api.baslangicDurumu.mockRejectedValue(new Error("Ağ hatası"));
    render(<BaslangicPage />);
    expect(await screen.findByText("Durum okunamadı")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tekrar dene/ })).toBeInTheDocument();
  });
});
