/**
 * Verilerimi Bağla — what a person sees after dropping files.
 *
 * The API is mocked with the shapes backend/tests/test_ingest.py pins, so
 * this checks the page's side of the contract: what was added and where it
 * goes, and that an ambiguous file asks and is re-sent with the choice.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const veriEkle = vi.fn();
vi.mock("@/lib/api/veri", () => ({
  veriTurleri: vi.fn().mockResolvedValue([
    { tur: "headcount", alan: "chro", etiket: "Personel listesi" },
    { tur: "policies", alan: "compliance", etiket: "Şirket politikaları" },
  ]),
  veriEkle: (...args: unknown[]) => veriEkle(...args),
  epostaAdresi: vi.fn().mockResolvedValue({ acik: true, adres: "veri+abc123def456@veri.example.com",
                                           nasil: ["Ekstre e-postalarını bu adrese iletin."] }),
  epostaAdresiYenile: vi.fn(),
  gelenEpostalar: vi.fn().mockResolvedValue([
    { id: "m1", alindi: "2024-02-01T09:00:00Z", gonderen: "ekstre@banka.example", konu: "Ocak ekstresi",
      dosyalar: [{ dosya: "ekstre.xlsx", durum: "eklendi", etiket: "Banka ekstresi", sayfa: "/cfo" },
                 { dosya: "ekstre.xlsx", durum: "onceden_alindi" }] },
  ]),
}));

const setActiveCFOJob = vi.fn();
vi.mock("@/store/companyContext", () => ({
  useCompanyContextStore: () => ({ setActiveCFOJob }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) =>
    React.createElement("a", { href, ...rest }, children),
}));

import BaglanPage from "@/app/(dashboard)/baglan/page";

const tanima = (over: Record<string, unknown>) => ({
  durum: "kesin", tur: null, alan: null, etiket: null, adaylar: [], satir_sayisi: 0,
  sayfa: null, ozet: "", sutunlar: [], ...over,
});

function drop(files: File[]) {
  fireEvent.drop(screen.getByRole("button", { name: /dosya bırakın/i }), { dataTransfer: { files } });
}

describe("Verilerimi Bağla", () => {
  beforeEach(() => {
    veriEkle.mockReset();
    setActiveCFOJob.mockReset();
  });

  it("shows what each file was recognised as and links the page it feeds", async () => {
    veriEkle.mockResolvedValue({
      job_id: "job-1",
      dosyalar: [
        { dosya: "personel.xlsx", durum: "eklendi", sayfa: "/chro", job_id: "job-1", mesaj: "Personel listesi eklendi.",
          tanima: tanima({ tur: "headcount", alan: "chro", etiket: "Personel listesi", satir_sayisi: 42,
                           adaylar: [{ tur: "headcount", alan: "chro", etiket: "Personel listesi",
                                       eslesen: { name: "Ad Soyad", salary: "Brüt Maaş" }, eksik: [] }] }) },
      ],
    });
    render(<BaglanPage />);
    drop([new File(["x"], "personel.xlsx")]);

    const kart = within((await screen.findByText("personel.xlsx")).closest("li") as HTMLElement);
    expect(kart.getByText("Personel listesi")).toBeInTheDocument();
    expect(kart.getByText(/42 kayıt/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sayfaya git/ })).toHaveAttribute("href", "/chro");
    expect(setActiveCFOJob).toHaveBeenCalledWith("job-1");
    // No job id from this browser's storage is sent: it may be an earlier login's.
    expect(veriEkle.mock.calls[0][2]).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: /Hangi sütunlar okundu/ }));
    expect(screen.getByText("Brüt Maaş")).toBeInTheDocument();
  });

  it("asks when a file fits two kinds, and re-sends it with the choice", async () => {
    const aday = (tur: string, alan: string, etiket: string) => ({ tur, alan, etiket, eslesen: {}, eksik: [] });
    veriEkle.mockResolvedValueOnce({
      job_id: null,
      dosyalar: [{ dosya: "k.csv", durum: "secim_gerekli", mesaj: "Bu dosya birden fazla türe uyuyor.",
                   tanima: tanima({ durum: "belirsiz", adaylar: [aday("policies", "compliance", "Şirket politikaları"),
                                                               aday("findings", "audit", "Denetim bulguları")] }) }],
    });
    render(<BaglanPage />);
    const file = new File(["x"], "k.csv");
    drop([file]);

    expect(await screen.findByText("Bu dosya birden fazla türe uyuyor.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Sayfaya git/ })).not.toBeInTheDocument();

    veriEkle.mockResolvedValueOnce({
      job_id: "job-2",
      dosyalar: [{ dosya: "k.csv", durum: "eklendi", sayfa: "/compliance", mesaj: "Şirket politikaları eklendi.",
                   tanima: tanima({ tur: "policies", alan: "compliance", etiket: "Şirket politikaları" }) }],
    });
    fireEvent.change(screen.getByLabelText("Bu dosya:"), { target: { value: "policies" } });
    fireEvent.click(screen.getByRole("button", { name: "Bu türde ekle" }));

    await waitFor(() => expect(veriEkle).toHaveBeenCalledTimes(2));
    expect(veriEkle.mock.calls[1][0]).toEqual([file]);
    expect(veriEkle.mock.calls[1][1]).toEqual({ "k.csv": "policies" });
    expect(await screen.findByRole("link", { name: /Sayfaya git/ })).toHaveAttribute("href", "/compliance");
  });

  it("shows the mail address and what arrived through it", async () => {
    render(<BaglanPage />);
    expect(await screen.findByText("veri+abc123def456@veri.example.com")).toBeInTheDocument();
    expect(await screen.findByText("Ocak ekstresi")).toBeInTheDocument();
    expect(screen.getByText(/daha önce alınmış/)).toBeInTheDocument();
    // Renewal asks first: mail to the old address stops being accepted.
    fireEvent.click(screen.getByRole("button", { name: "Adresi yenile" }));
    expect(screen.getByText(/Eski adrese gelen posta artık alınmaz/)).toBeInTheDocument();
  });

  it("says in words why a file was refused", async () => {
    veriEkle.mockResolvedValue({
      job_id: null,
      dosyalar: [{ dosya: "eski.xls", durum: "reddedildi",
                   mesaj: "Bu eski Excel biçimi (.xls) okunamıyor.", tanima: tanima({ durum: "taninmadi" }) }],
    });
    render(<BaglanPage />);
    drop([new File(["x"], "eski.xls")]);
    expect(await screen.findByText(/eski Excel biçimi/)).toBeInTheDocument();
  });
});
