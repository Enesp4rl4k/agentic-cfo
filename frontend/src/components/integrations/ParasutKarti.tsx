"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, RefreshCw, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  disconnectParasut, parasutBaglan, parasutDurum, parasutFirmaSec, parasutOtomatik, syncParasut,
  type OtomatikAralik, type ParasutDurum, type ParasutSyncSonucu,
} from "@/lib/api/erp";

const DONUS: Record<string, { tur: "ok" | "hata"; metin: string }> = {
  baglandi: { tur: "ok", metin: "Paraşüt bağlandı." },
  firma_sec: { tur: "ok", metin: "Paraşüt'e giriş yapıldı. Hangi firmanın verisinin alınacağını seçin." },
  hata: { tur: "hata", metin: "Paraşüt bağlantısı tamamlanamadı. Tekrar deneyin." },
  iptal: { tur: "hata", metin: "Paraşüt girişi iptal edildi." },
};

/**
 * Paraşüt in one step: press the button, log in at Paraşüt, come back connected.
 *
 * It used to ask for an OAuth client id and secret — a developer application
 * the person had to register at Paraşüt first.
 */
export function ParasutKarti() {
  const params = useSearchParams();
  const donus = DONUS[params.get("parasut") ?? ""];
  const [durum, setDurum] = useState<ParasutDurum | null>(null);
  const [mesgul, setMesgul] = useState<string | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [firma, setFirma] = useState("");
  const [sonuc, setSonuc] = useState<ParasutSyncSonucu | null>(null);

  const yukle = useCallback(() => {
    parasutDurum().then(setDurum).catch((e) => setHata(e instanceof Error ? e.message : "Durum alınamadı."));
  }, []);
  useEffect(yukle, [yukle]);

  async function calistir(ad: string, is: () => Promise<void>) {
    setMesgul(ad);
    setHata(null);
    try {
      await is();
    } catch (e) {
      setHata(e instanceof Error ? e.message : "İşlem başarısız.");
    } finally {
      setMesgul(null);
    }
  }

  if (!durum) return null;
  const b = durum.baglanti;
  const bagli = b?.status === "active";
  const firmaSecimi = b?.status === "firma_secimi";

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">Paraşüt</h2>
          <p className="text-xs text-muted-foreground">
            {bagli ? b?.display_name : "Satış ve gider faturalarınız otomatik olarak alınır ve analiz edilir."}
          </p>
        </div>
        {bagli && <CheckCircle2 className="h-5 w-5 text-emerald-400" aria-label="Bağlı" />}
      </div>

      {donus && (
        <p role="status" className={donus.tur === "ok" ? "text-xs text-emerald-400" : "text-xs text-red-400"}>
          {donus.metin}
        </p>
      )}

      {!durum.acik ? (
        <p className="text-xs text-muted-foreground">
          Paraşüt bağlantısı bu sunucuda henüz açılmadı. Paraşüt&apos;ten aldığınız Excel dosyalarını{" "}
          <Link href="/baglan" className="text-primary hover:underline">Verilerimi Bağla</Link> sayfasından
          yükleyebilirsiniz.
        </p>
      ) : firmaSecimi ? (
        <div className="flex flex-wrap items-center gap-2">
          {durum.firmalar.length > 0 ? (
            <select
              aria-label="Firma"
              value={firma}
              onChange={(e) => setFirma(e.target.value)}
              className="rounded-md border border-border bg-card px-2 py-1 text-xs"
            >
              <option value="">Firma seçin…</option>
              {durum.firmalar.map((f) => <option key={f.id} value={f.id}>{f.ad}</option>)}
            </select>
          ) : (
            <input
              aria-label="Paraşüt firma numarası"
              inputMode="numeric"
              placeholder="Paraşüt firma numarası"
              value={firma}
              onChange={(e) => setFirma(e.target.value.replace(/\D/g, ""))}
              className="rounded-md border border-border bg-card px-2 py-1 text-xs"
            />
          )}
          <Button
            size="sm"
            disabled={!firma || mesgul !== null}
            onClick={() => calistir("firma", async () => { await parasutFirmaSec(firma); yukle(); })}
          >
            Kaydet
          </Button>
        </div>
      ) : bagli && b ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={mesgul !== null}
              onClick={() => calistir("sync", async () => { setSonuc(await syncParasut(b.id)); yukle(); })}
            >
              {mesgul === "sync"
                ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                : <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden="true" />}
              Faturaları şimdi al
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={mesgul !== null}
              onClick={() => calistir("kes", async () => { await disconnectParasut(b.id); yukle(); })}
            >
              <Unplug className="mr-1 h-3.5 w-3.5" aria-hidden="true" /> Bağlantıyı kes
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label htmlFor="parasut-otomatik">Otomatik al:</label>
            <select
              id="parasut-otomatik"
              value={!b.auto_sync_enabled ? "kapali" : b.sync_interval_hours >= 168 ? "haftalik" : "gunluk"}
              disabled={mesgul !== null}
              onChange={(e) => {
                const aralik = e.target.value as OtomatikAralik;
                void calistir("otomatik", async () => { await parasutOtomatik(aralik); yukle(); });
              }}
              className="rounded-md border border-border bg-card px-2 py-1 text-xs"
            >
              <option value="gunluk">Her gün</option>
              <option value="haftalik">Her hafta</option>
              <option value="kapali">Kapalı</option>
            </select>
            <span className="text-muted-foreground">Yalnızca yeni ya da değişen faturalar analiz edilir.</span>
          </div>
          {b.last_sync_at && (
            <p className="text-xs text-muted-foreground">
              Son alım: {new Date(b.last_sync_at).toLocaleString("tr-TR")}
              {b.last_sync_status === "error" ? ` — başarısız: ${b.last_error ?? ""}` : ` — ${b.last_sync_count ?? 0} fatura`}
            </p>
          )}
          {sonuc && (
            <p className="text-xs">
              {sonuc.durum === "analiz_baslatildi"
                ? <>{sonuc.sync_count} fatura alındı ve analiz başlatıldı. <Link href="/cfo" className="text-primary hover:underline">CFO sayfası</Link></>
                : (sonuc.mesaj ?? "Yeni fatura yok.")}
            </p>
          )}
        </div>
      ) : (
        <Button
          size="sm"
          disabled={mesgul !== null}
          onClick={() => calistir("baglan", async () => { window.location.href = await parasutBaglan(); })}
        >
          {mesgul === "baglan" && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          Paraşüt ile bağlan
        </Button>
      )}

      {hata && <p role="alert" className="text-xs text-red-400">{hata}</p>}
    </Card>
  );
}
