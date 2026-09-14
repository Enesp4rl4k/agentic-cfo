"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, ArrowRight, CheckCircle2, ChevronDown, FileSpreadsheet, HelpCircle, Loader2, UploadCloud, XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useCompanyContextStore } from "@/store/companyContext";
import { veriEkle, veriTurleri, type DosyaSonucu, type TurSecenegi } from "@/lib/api/veri";

const ALAN_ADI: Record<string, string> = {
  cfo: "Finans", cto: "Teknoloji", chro: "İnsan Kaynakları", cmo: "Pazarlama",
  coo: "Operasyon", risk: "Risk", audit: "İç Denetim", compliance: "Uyum",
};
const KABUL = ".xlsx,.csv,.pdf,.txt,.xls";

/**
 * Verilerimi bağla.
 *
 * For someone who exports a list from the program they already use and does
 * not know what a "source type" is. They drop the files; each is recognised
 * from its columns and put where it belongs. When a file fits more than one
 * kind, or none, the page asks — it never files it somewhere on a guess.
 */
export default function BaglanPage() {
  const { setActiveCFOJob } = useCompanyContextStore();
  const [sonuclar, setSonuclar] = useState<DosyaSonucu[]>([]);
  const [dosyalar, setDosyalar] = useState<Record<string, File>>({});
  const [yukleniyor, setYukleniyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const [surukle, setSurukle] = useState(false);
  const [turler, setTurler] = useState<TurSecenegi[]>([]);
  const secici = useRef<HTMLInputElement>(null);

  useEffect(() => {
    veriTurleri().then(setTurler).catch(() => setTurler([]));
  }, []);

  async function gonder(files: File[], secimler?: Record<string, string>) {
    if (!files.length) return;
    setYukleniyor(true);
    setHata(null);
    setDosyalar((d) => ({ ...d, ...Object.fromEntries(files.map((f) => [f.name, f])) }));
    try {
      // No job id is sent: the one kept in this browser may belong to an earlier
      // login. The server attaches files to the organisation's latest analysis.
      const out = await veriEkle(files, secimler);
      if (out.job_id && out.dosyalar.some((x) => x.durum === "eklendi")) {
        setActiveCFOJob(out.job_id);
      }
      setSonuclar((prev) => {
        const yeni = new Map(prev.map((s) => [s.dosya, s]));
        out.dosyalar.forEach((s) => yeni.set(s.dosya, s));
        return Array.from(yeni.values());
      });
    } catch (e) {
      setHata(e instanceof Error ? e.message : "Dosyalar gönderilemedi.");
    } finally {
      setYukleniyor(false);
    }
  }

  function buTurdeEkle(dosya: string, tur: string) {
    const f = dosyalar[dosya];
    if (f) void gonder([f], { [dosya]: tur });
  }

  const eklenen = sonuclar.filter((s) => s.durum === "eklendi");
  const acilanSayfalar = useMemo(
    () => Array.from(new Set(eklenen.map((s) => s.sayfa).filter(Boolean))) as string[],
    [eklenen],
  );
  const gruplu = useMemo(() => {
    const m = new Map<string, TurSecenegi[]>();
    turler.forEach((t) => m.set(t.alan, [...(m.get(t.alan) ?? []), t]));
    return m;
  }, [turler]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Verilerimi Bağla</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Kullandığınız programdan (muhasebe, banka, bordro, reklam paneli) aldığınız dosyaları buraya
          bırakın. Ne olduklarını sütunlarından sistem anlar; sütun adlarını değiştirmenize gerek yok.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-4">
          <div
            role="button"
            tabIndex={0}
            aria-label="Dosya bırakın ya da seçin"
            onClick={() => secici.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") secici.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setSurukle(true); }}
            onDragLeave={() => setSurukle(false)}
            onDrop={(e) => {
              e.preventDefault();
              setSurukle(false);
              void gonder(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              surukle ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-muted/30",
            )}
          >
            {yukleniyor ? (
              <Loader2 className="h-10 w-10 animate-spin text-primary" aria-hidden="true" />
            ) : (
              <UploadCloud className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
            )}
            <div>
              <p className="font-medium">
                {yukleniyor ? "Dosyalar okunuyor…" : "Dosyaları buraya sürükleyin ya da tıklayıp seçin"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Excel (.xlsx), CSV ya da PDF · birden fazla dosyayı birlikte bırakabilirsiniz · en fazla 10 dosya
              </p>
            </div>
            <input
              ref={secici}
              type="file"
              multiple
              accept={KABUL}
              className="hidden"
              onChange={(e) => {
                void gonder(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
          </div>

          {hata && (
            <p role="alert" className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              {hata}
            </p>
          )}

          {acilanSayfalar.length > 0 && (
            <Card className="flex flex-wrap items-center gap-2 p-3">
              <span className="text-sm">Verisi eklenen sayfalar:</span>
              {acilanSayfalar.map((s) => (
                <Link
                  key={s}
                  href={s}
                  className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                >
                  {ALAN_ADI[s.slice(1)] ?? s} <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Link>
              ))}
            </Card>
          )}

          <ul className="space-y-3">
            {sonuclar.map((s) => (
              <DosyaKarti
                key={s.dosya}
                sonuc={s}
                turler={turler}
                mesgul={yukleniyor}
                tekrarGonderilebilir={Boolean(dosyalar[s.dosya])}
                onSec={(tur) => buTurdeEkle(s.dosya, tur)}
              />
            ))}
          </ul>
        </div>

        <aside className="space-y-3">
          <Card className="p-4">
            <p className="flex items-center gap-1.5 text-sm font-semibold">
              <HelpCircle className="h-4 w-4" aria-hidden="true" /> Neleri bağlayabilirim?
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Önce bir banka ekstresi ya da muhasebe dosyası ekleyin; diğer dosyalar ona bağlanır.
            </p>
            <div className="mt-3 space-y-3">
              {Array.from(gruplu.entries()).map(([alan, liste]) => (
                <div key={alan}>
                  <p className="text-xs font-medium">{ALAN_ADI[alan] ?? alan}</p>
                  <ul className="mt-0.5 space-y-0.5">
                    {liste.map((t) => (
                      <li key={t.tur} className="text-xs text-muted-foreground">{t.etiket}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function DosyaKarti({
  sonuc, turler, mesgul, tekrarGonderilebilir, onSec,
}: {
  sonuc: DosyaSonucu;
  turler: TurSecenegi[];
  mesgul: boolean;
  tekrarGonderilebilir: boolean;
  onSec: (tur: string) => void;
}) {
  const [acik, setAcik] = useState(false);
  const [secilen, setSecilen] = useState("");
  const { durum, tanima } = sonuc;
  const ikon =
    durum === "eklendi" ? <CheckCircle2 className="h-5 w-5 text-emerald-400" aria-hidden="true" />
    : durum === "secim_gerekli" ? <HelpCircle className="h-5 w-5 text-amber-400" aria-hidden="true" />
    : durum === "reddedildi" ? <XCircle className="h-5 w-5 text-red-400" aria-hidden="true" />
    : <AlertCircle className="h-5 w-5 text-amber-400" aria-hidden="true" />;
  const aday = tanima.adaylar[0];
  // Choices: the candidates when recognition was torn, every kind when it found none.
  const secenekler = durum === "secim_gerekli" ? tanima.adaylar : durum === "taninmadi" ? turler : [];

  return (
    <li>
      <Card className="space-y-2 p-4">
        <div className="flex items-start gap-3">
          {ikon}
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 truncate text-sm font-medium">
              <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              {sonuc.dosya}
            </p>
            {durum === "eklendi" && tanima.etiket && (
              <p className="text-sm">
                <span className="font-medium">{tanima.etiket}</span>
                {tanima.satir_sayisi > 0 && (
                  <span className="text-muted-foreground"> · {tanima.satir_sayisi} kayıt</span>
                )}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {sonuc.mesaj ?? tanima.ozet}
            </p>
          </div>
          {durum === "eklendi" && sonuc.sayfa && (
            <Link href={sonuc.sayfa} className="shrink-0 text-xs font-medium text-primary hover:underline">
              Sayfaya git →
            </Link>
          )}
        </div>

        {durum === "eklendi" && aday && Object.keys(aday.eslesen).length > 0 && (
          <div>
            <button
              type="button"
              onClick={() => setAcik((v) => !v)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              aria-expanded={acik}
            >
              <ChevronDown className={cn("h-3 w-3 transition-transform", acik && "rotate-180")} aria-hidden="true" />
              Hangi sütunlar okundu
            </button>
            {acik && (
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {Object.values(aday.eslesen).map((h) => (
                  <li key={h} className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{h}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {secenekler.length > 0 && tekrarGonderilebilir && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-2">
            <label htmlFor={`tur-${sonuc.dosya}`} className="text-xs">Bu dosya:</label>
            <select
              id={`tur-${sonuc.dosya}`}
              value={secilen}
              onChange={(e) => setSecilen(e.target.value)}
              className="rounded-md border border-border bg-card px-2 py-1 text-xs"
            >
              <option value="">Seçin…</option>
              {secenekler.map((t) => (
                <option key={t.tur} value={t.tur}>
                  {t.etiket} ({ALAN_ADI[t.alan] ?? t.alan})
                </option>
              ))}
            </select>
            <Button size="sm" variant="outline" disabled={!secilen || mesgul} onClick={() => onSec(secilen)}>
              Bu türde ekle
            </Button>
          </div>
        )}
      </Card>
    </li>
  );
}
