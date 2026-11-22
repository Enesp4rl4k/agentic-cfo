/**
 * Başlangıç — the steps come from the organisation's data, and each state says
 * what to do next. The old guide was a slideshow whose progress lived in the
 * browser, so none of this could be asserted.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { api } = vi.hoisted(() => ({
  api: { baslangicDurumu: vi.fn(), firmaOlustur: vi.fn() },
}));
vi.mock("@/lib/api/baslangic", () => api);
vi.mock("next/link", async () => (await import("./dashboard-mocks")).nextLinkModule);
vi.mock("@/lib/api/ledger", async () => (await import("./dashboard-mocks")).ledgerModule);
// The page renders through useI18n, which resolves the org locale — these assertions pin a tr-TR org's copy.
vi.mock("@/hooks/useOrgSettings", async () => (await import("./dashboard-mocks")).orgSettingsModule);

import BaslangicPage from "@/app/(dashboard)/baslangic/page";
import { ledgerSpies, renderWithQuery } from "./dashboard-mocks";

type Over = Record<string, unknown>;

/** What the API answers; the per-status counts are derived from the parts the test sets, as the server does. */
const durum = (over: Over = {}) => {
  const merged = {
    firma: { var: true, ad: "Kobi A.Ş." },
    veri: { analiz_sayisi: 1, parasut_bagli: false },
    son_analiz: null as { durum: string } | null,
    tamamlanan_analiz: 0,
    onay_bekleyen: [] as unknown[],
    otomatik: { eposta: false, parasut_otomatik: false },
    ...over,
  };
  const running = ["pending", "ingesting", "analyzing"].includes(merged.son_analiz?.durum ?? "");
  return {
    analizler: {
      calisan: running ? 1 : 0,
      onay_bekleyen: merged.onay_bekleyen.length,
      tamamlanan: merged.tamamlanan_analiz,
      basarisiz: merged.son_analiz?.durum === "failed" ? 1 : 0,
    },
    ...merged,
  };
};

/** One analysis waiting for the owner, as `onay_bekleyen` lists it. */
const bekleyen = (over: Over = {}) => ({
  id: "job-1", dosya: "ekstre.csv", guven: null, bakiye_kanitli: true, olusturma: null,
  nedenler: [{ code: "rows_waiting", count: 6, all_rows: true, summary: "6 kaydın para birimi bilinmiyor." }],
  ...over,
});

const renderPage = () => renderWithQuery(<BaslangicPage />);

/** The radar as the API answers it: starting cash proven by a statement, or unknown. */
const radar = (over: Record<string, unknown> = {}) => ({
  starting_cash_cents: 1_250_000_00,
  starting_cash_as_of: "2026-11-14",
  ...over,
});

describe("Başlangıç", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    ledgerSpies.getCashRadar.mockReset();
    ledgerSpies.getCashRadar.mockResolvedValue(radar());
  });

  it("counts the steps the organisation has actually finished", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 2 }));
    renderPage();
    expect(await screen.findByText("Kurulum tamam")).toBeInTheDocument();
    expect(screen.getByText("4/4")).toBeInTheDocument();
  });

  it("asks for a company name when there is none, and creates it", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ firma: { var: false, ad: null }, veri: { analiz_sayisi: 0, parasut_bagli: false } }));
    api.firmaOlustur.mockResolvedValue(undefined);
    renderPage();
    expect(await screen.findByText("4 adımdan 0'i tamam")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Firma adı"), { target: { value: "Yıldız Tekstil" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(api.firmaOlustur).toHaveBeenCalledWith("Yıldız Tekstil"));
  });

  it("says an analysis is waiting for approval, with why, and links to the one place that decides", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-1", durum: "awaiting_review", onay_bekliyor: true, guven: 0.62,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
      onay_bekleyen: [bekleyen({ guven: 0.62, nedenler: [{ code: "confidence_low", min_confidence: 0.62, threshold: 0.8 }] })],
    }));
    renderPage();
    expect(await screen.findByText("Analiz onayınızı bekliyor")).toBeInTheDocument();
    expect(screen.getByText("Güven puanı %62; %80 altındaki sonuçlar onayla kullanılır.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Önce sonuçlara bakayım/ })).toHaveAttribute("href", "/pnl?job=job-1");
    // One click to where it is answered; the setup page itself does not approve.
    expect(screen.getAllByRole("link", { name: /Onay bekleyenleri aç/ })[0]).toHaveAttribute("href", "/onay");
    expect(screen.queryByRole("button", { name: /Onayla/ })).toBeNull();
  });

  it("with one analysis completed and a statement held, the setup is not done and the held one is shown", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      tamamlanan_analiz: 1,
      son_analiz: { id: "job-1", durum: "awaiting_review", onay_bekliyor: true, guven: null,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
      onay_bekleyen: [bekleyen()],
    }));
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    renderPage();
    expect(await screen.findByText("1 analiz onayınızı bekliyor")).toBeInTheDocument();
    expect(screen.getByText("1 analiz tamamlandı.")).toBeInTheDocument();
    expect(screen.queryByText("Kurulum tamam")).toBeNull();
    expect(screen.getByText("2/4")).toBeInTheDocument();
  });

  it("says the statement is waiting for approval, not that it has no balance, while it is held", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      tamamlanan_analiz: 1,
      onay_bekleyen: [bekleyen()],
    }));
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    renderPage();
    expect(await screen.findByText("Ekstreniz onayınızı bekliyor")).toBeInTheDocument();
    expect(screen.getByText(/satır bakiyeleri birbirini tutuyor, dosyada eksik yok/)).toBeInTheDocument();
    expect(screen.queryByText(/bakiye sütunu yok/)).toBeNull();
    expect(screen.queryByText("Kanıtlanmış banka bakiyesi yok")).toBeNull();
  });

  it("does not claim the held file proves a balance when the run does not say so", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      tamamlanan_analiz: 1,
      onay_bekleyen: [bekleyen({ bakiye_kanitli: false })],
    }));
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    renderPage();
    expect(await screen.findByText("Onayınızı bekleyen analiz var")).toBeInTheDocument();
    expect(screen.queryByText("Ekstreniz onayınızı bekliyor")).toBeNull();
  });

  it("says the opening balance waits for the running analysis, not that there is none", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      tamamlanan_analiz: 1,
      son_analiz: { id: "job-2", durum: "analyzing", onay_bekliyor: false, guven: null,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
    }));
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    renderPage();
    expect(await screen.findByText("Analiz sürüyor; bitince başlangıç bakiyesi burada görünür.")).toBeInTheDocument();
    expect(screen.queryByText("Kanıtlanmış banka bakiyesi yok")).toBeNull();
  });

  it("keeps the balance a completed statement proved even while another analysis waits", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1, onay_bekleyen: [bekleyen({ bakiye_kanitli: false })] }));
    renderPage();
    expect(await screen.findByText(/14\.11\.2026 tarihinde .*1\.250\.000/)).toBeInTheDocument();
    expect(screen.getByText("1 analiz onayınızı bekliyor")).toBeInTheDocument();
  });

  it("shows a failed analysis with its reason and a way to retry", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-2", durum: "failed", onay_bekliyor: false, guven: null,
                    dosya: "ekstre.csv", hata: "Tarih sütunu bulunamadı.", olusturma: null },
    }));
    renderPage();
    expect(await screen.findByText("Tarih sütunu bulunamadı.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dosyayı yeniden bağla/ })).toHaveAttribute("href", "/baglan");
  });

  it("says so when the status cannot be read, instead of an empty page", async () => {
    api.baslangicDurumu.mockRejectedValue(new Error("Ağ hatası"));
    renderPage();
    expect(await screen.findByText("Durum okunamadı")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tekrar dene/ })).toBeInTheDocument();
  });

  it("says the first report is ready and where to read it once every step is done", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    renderPage();
    expect(await screen.findByText("İlk raporun hazır")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nakit radarını aç" })).toHaveAttribute("href", "/nakit-radari");
    expect(screen.getByRole("link", { name: "Seyir Defteri'ni aç" })).toHaveAttribute("href", "/bulten");
  });

  it("does not say the report is ready while a step is still open", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 0 }));
    renderPage();
    await screen.findByText(/4 adımdan/);
    expect(screen.queryByText("İlk raporun hazır")).toBeNull();
  });

  it("shows the route being calculated while an analysis is in flight, and only then", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({
      son_analiz: { id: "job-2", durum: "analyzing", onay_bekliyor: false, guven: null,
                    dosya: "ekstre.csv", hata: null, olusturma: null },
    }));
    renderPage();
    expect(await screen.findByText("Rota hesaplanıyor")).toBeInTheDocument();
    expect(screen.getByText(/ekstre\.csv işleniyor/)).toBeInTheDocument();
  });

  it("numbers the steps in order", async () => {
    api.baslangicDurumu.mockResolvedValue(durum());
    renderPage();
    await screen.findByText(/4 adımdan/);
    for (const n of ["01", "02", "03", "04", "05"]) expect(screen.getByText(n)).toBeInTheDocument();
  });

  it("starts from the balance a statement proved, and asks the radar only once an analysis is complete", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    renderPage();
    expect(await screen.findByText(/14\.11\.2026 tarihinde .*1\.250\.000/)).toBeInTheDocument();
    expect(ledgerSpies.getCashRadar).toHaveBeenCalledTimes(1);
  });

  it("warns, as the radar page does, when the statement the balance rests on is old", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    ledgerSpies.getCashRadar.mockResolvedValue(
      radar({ opening_cash: { balance_cents: 1_250_000_00, as_of: "2026-11-14", age_days: 21, stale: true, stale_after_days: 7 } }),
    );
    renderPage();
    expect(await screen.findByText("Bu bakiye 21 gün önceki ekstreye dayanıyor")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Yeni ekstre yükle" })).toHaveAttribute("href", "/baglan");
    expect(screen.getByText(/14.11.2026 tarihinde/)).toBeInTheDocument();
  });

  it("says nothing about age when the balance is fresh", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    ledgerSpies.getCashRadar.mockResolvedValue(
      radar({ opening_cash: { balance_cents: 1_250_000_00, as_of: "2026-11-14", age_days: 1, stale: false, stale_after_days: 7 } }),
    );
    renderPage();
    await screen.findByText(/14.11.2026 tarihinde/);
    expect(screen.queryByText(/gün önceki ekstreye dayanıyor/)).toBeNull();
  });

  it("waits for the first analysis and does not read the radar before it", async () => {
    api.baslangicDurumu.mockResolvedValue(durum());
    renderPage();
    expect(await screen.findByText("İlk analiziniz bitince burada görünür.")).toBeInTheDocument();
    expect(ledgerSpies.getCashRadar).not.toHaveBeenCalled();
  });

  it("says the balance is unproven, never invents one, and points to a statement upload", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    ledgerSpies.getCashRadar.mockResolvedValue(radar({ starting_cash_cents: null, starting_cash_as_of: null }));
    renderPage();
    expect(await screen.findByText("Kanıtlanmış banka bakiyesi yok")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bakiyeli ekstre yükle/ })).toHaveAttribute("href", "/baglan");
    expect(screen.getByText(/Tamamlanan analizlerin hiçbirinde, satır bakiyeleri birbirini tutan bir banka ekstresi yok/)).toBeInTheDocument();
    expect(screen.queryByText("İlk raporun hazır")).toBeNull();
    expect(screen.getByText("3/4")).toBeInTheDocument();
  });

  it("says so when the radar cannot be read, and reads it again on request", async () => {
    api.baslangicDurumu.mockResolvedValue(durum({ tamamlanan_analiz: 1 }));
    ledgerSpies.getCashRadar.mockRejectedValueOnce(new Error("down"));
    renderPage();
    expect(await screen.findByText("Radar okunamadı.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Tekrar dene/ }));
    await waitFor(() => expect(screen.getByText("İlk raporun hazır")).toBeInTheDocument());
    expect(ledgerSpies.getCashRadar).toHaveBeenCalledTimes(2);
  });
});
