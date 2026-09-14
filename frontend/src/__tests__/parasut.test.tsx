/**
 * Paraşüt card — one button, never a developer key; states the backend returns
 * (backend/tests/test_parasut.py) shown in words.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api, nav } = vi.hoisted(() => ({
  api: {
    parasutDurum: vi.fn(),
    parasutBaglan: vi.fn(),
    parasutFirmaSec: vi.fn(),
    syncParasut: vi.fn(),
    disconnectParasut: vi.fn(),
    parasutOtomatik: vi.fn(),
  },
  nav: { query: "" },
}));
vi.mock("@/lib/api/erp", () => api);

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.query),
  usePathname: () => "/integrations",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => React.createElement("a", { href }, children),
}));

import { ParasutKarti } from "@/components/integrations/ParasutKarti";

const baglanti = (over: Record<string, unknown> = {}) => ({
  id: "i1", org_id: "o1", provider: "parasut", display_name: "Paraşüt · Kobi A.Ş.", status: "active",
  last_sync_at: null, last_sync_status: null, last_sync_count: null, last_error: null, next_sync_at: null,
  auto_sync_enabled: true, sync_interval_hours: 24, connected_at: null, token_expires_at: null, token_expired: false,
  ...over,
});

describe("ParasutKarti", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    nav.query = "";
  });

  it("offers one button and no key fields when not connected", async () => {
    api.parasutDurum.mockResolvedValue({ acik: true, baglanti: null, firmalar: [] });
    render(<ParasutKarti />);
    expect(await screen.findByRole("button", { name: "Paraşüt ile bağlan" })).toBeInTheDocument();
    expect(screen.queryByText(/Client/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says plainly when the server has no Paraşüt application, and points to file upload", async () => {
    api.parasutDurum.mockResolvedValue({ acik: false, baglanti: null, firmalar: [] });
    render(<ParasutKarti />);
    expect(await screen.findByText(/henüz açılmadı/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Verilerimi Bağla" })).toHaveAttribute("href", "/baglan");
  });

  it("asks which company after login, and saves the choice", async () => {
    nav.query = "parasut=firma_sec";
    api.parasutDurum.mockResolvedValue({
      acik: true, baglanti: baglanti({ status: "firma_secimi" }),
      firmalar: [{ id: "123456", ad: "Kobi A.Ş." }, { id: "777", ad: "Kobi Ltd." }],
    });
    api.parasutFirmaSec.mockResolvedValue(baglanti());
    render(<ParasutKarti />);
    expect(await screen.findByText(/Hangi firmanın/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Firma"), { target: { value: "777" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(api.parasutFirmaSec).toHaveBeenCalledWith("777"));
  });

  it("pulls invoices on demand and says an analysis started", async () => {
    api.parasutDurum.mockResolvedValue({ acik: true, baglanti: baglanti(), firmalar: [] });
    api.syncParasut.mockResolvedValue({ durum: "analiz_baslatildi", sync_count: 12, job_id: "job-9" });
    render(<ParasutKarti />);
    fireEvent.click(await screen.findByRole("button", { name: /Faturaları şimdi al/ }));
    expect(await screen.findByText(/12 fatura alındı ve analiz başlatıldı/)).toBeInTheDocument();
    expect(api.syncParasut).toHaveBeenCalledWith("i1");
  });

  it("says when nothing changed instead of starting another analysis", async () => {
    api.parasutDurum.mockResolvedValue({ acik: true, baglanti: baglanti(), firmalar: [] });
    api.syncParasut.mockResolvedValue({ durum: "degisiklik_yok", sync_count: 12, job_id: "job-9",
                                        mesaj: "Son alımdan bu yana yeni ya da değişen fatura yok; son analiz güncel." });
    render(<ParasutKarti />);
    fireEvent.click(await screen.findByRole("button", { name: /Faturaları şimdi al/ }));
    expect(await screen.findByText(/değişen fatura yok/)).toBeInTheDocument();
    expect(screen.queryByText(/analiz başlatıldı/)).not.toBeInTheDocument();
  });

  it("lets the person choose how often invoices are pulled", async () => {
    api.parasutDurum.mockResolvedValue({ acik: true, baglanti: baglanti(), firmalar: [] });
    api.parasutOtomatik.mockResolvedValue(baglanti({ sync_interval_hours: 168 }));
    render(<ParasutKarti />);
    fireEvent.change(await screen.findByLabelText("Otomatik al:"), { target: { value: "haftalik" } });
    await waitFor(() => expect(api.parasutOtomatik).toHaveBeenCalledWith("haftalik"));
  });

  it("shows a failed pull as a failure", async () => {
    api.parasutDurum.mockResolvedValue({
      acik: true, firmalar: [],
      baglanti: baglanti({ last_sync_at: "2024-02-01T09:00:00Z", last_sync_status: "error", last_error: "Paraşüt sales_invoices isteği başarısız (403)." }),
    });
    render(<ParasutKarti />);
    expect(await screen.findByText(/başarısız: Paraşüt sales_invoices/)).toBeInTheDocument();
  });
});
