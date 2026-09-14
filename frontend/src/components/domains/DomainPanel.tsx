"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, FileUp, Loader2, PlayCircle, Receipt } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn, formatCurrency } from "@/lib/utils";
import {
  getDomain,
  runDomain,
  uploadDomainFile,
  type Alan,
  type AlanKodu,
} from "@/lib/api/domains";

/**
 * A domain's single entry point: real data, or what is missing and how to get it.
 *
 * This replaces the "Otomatik Analiz" banners that showed kernel estimates —
 * a health score, a vulnerability count, a velocity trend — derived from CFO
 * figures and sector constants for a company that had uploaded no domain data.
 * Nothing here is estimated. Without files the panel shows only the figures
 * the CFO books really contain, each with its source, and a way to add data
 * written for someone who does not know what a CSV is.
 */
export function DomainPanel({
  alan,
  jobId,
  onResult,
}: {
  alan: AlanKodu;
  jobId: string | null;
  onResult?: (sonuc: Record<string, unknown>) => void;
}) {
  const [data, setData] = useState<Alan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pickers = useRef<Record<string, HTMLInputElement | null>>({});

  const refresh = useCallback(async () => {
    if (!jobId) return;
    try {
      setData(await getDomain(jobId, alan));
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "durum alınamadı");
    }
  }, [jobId, alan]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function upload(tip: string, file: File) {
    if (!jobId) return;
    setBusy(tip);
    setErr(null);
    try {
      await uploadDomainFile(jobId, alan, tip, file);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "dosya yüklenemedi");
    } finally {
      setBusy(null);
    }
  }

  async function run() {
    if (!jobId) return;
    setBusy("run");
    setErr(null);
    try {
      const out = await runDomain(jobId, alan);
      setData(out);
      if (out.sonuc) onResult?.(out.sonuc);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "analiz çalışmadı");
    } finally {
      setBusy(null);
    }
  }

  if (!jobId) {
    return (
      <Card className="p-4 text-sm text-muted-foreground">
        Önce bir banka ekstresi ya da muhasebe dosyası yükleyin; bu alanın dosyaları o işe eklenir.
      </Card>
    );
  }
  if (!data) {
    return (
      <Card className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        {err ?? (<><Loader2 className="h-4 w-4 animate-spin" /> Yükleniyor…</>)}
      </Card>
    );
  }

  const hazir = data.durum === "hazir" || data.durum === "analiz_edildi";
  const yuklenen = data.kaynaklar.filter((k) => k.yuklendi).length;

  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">{data.ad}</p>
          <p className="text-xs text-muted-foreground">
            {data.durum === "analiz_edildi"
              ? `Yüklediğiniz ${yuklenen} dosyayla analiz edildi.`
              : hazir
                ? "Veri hazır — analizi başlatabilirsiniz."
                : data.hepsi_gerekli
                  ? `Bu alan için ${data.kaynaklar.length} dosyanın hepsi gerekir (${yuklenen} yüklendi).`
                  : "Bu alan için henüz veri yok. Aşağıdakilerden en az birini ekleyin."}
          </p>
        </div>
        <Button size="sm" onClick={run} disabled={!hazir || busy !== null} className="gap-1.5">
          {busy === "run" ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
          Analiz et
        </Button>
      </div>

      {data.cfo_gercek.kalemler.length > 0 && (
        <div className="rounded-md border border-border bg-muted/20 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium">
            <Receipt className="h-3.5 w-3.5" /> Finansal kayıtlarınızda zaten görünen
          </p>
          <ul className="space-y-1.5">
            {data.cfo_gercek.kalemler.map((k) => (
              <li key={k.kategori} className="text-xs">
                <span className="text-foreground">{k.etiket}: </span>
                <span className="font-mono font-semibold tabular-nums">
                  {k.tutar_kurus !== undefined
                    ? formatCurrency(k.tutar_kurus / 100)
                    : `${k.deger} ${k.birim ?? ""}`}
                </span>
                {k.gelire_orani != null && (
                  <span className="text-muted-foreground"> · gelirin %{(k.gelire_orani * 100).toFixed(1)}&apos;i</span>
                )}
                <span className="block text-[11px] text-muted-foreground">{k.kaynak}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="space-y-2">
        {data.kaynaklar.map((k) => (
          <li key={k.tip} className="flex items-start gap-3 rounded-md border border-border/60 p-2.5">
            {k.yuklendi ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
            ) : (
              <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm">
                {k.etiket}
                {k.dosya && <span className="ml-2 font-mono text-xs text-muted-foreground">{k.dosya}</span>}
              </p>
              <p className="text-xs text-muted-foreground">{k.nasil}</p>
            </div>
            <input
              ref={(el) => { pickers.current[k.tip] = el; }}
              type="file"
              accept=".csv,.xlsx,.xls,.txt"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void upload(k.tip, f);
                e.target.value = "";
              }}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() => pickers.current[k.tip]?.click()}
              className={cn("shrink-0 gap-1.5", k.yuklendi && "text-muted-foreground")}
            >
              {busy === k.tip ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileUp className="h-3.5 w-3.5" />}
              {k.yuklendi ? "Değiştir" : "Dosya seç"}
            </Button>
          </li>
        ))}
      </ul>

      {data.neden && data.durum !== "analiz_edildi" && (
        <p className="text-xs text-muted-foreground">{data.neden}</p>
      )}
      {err && <p className="text-xs text-red-400">{err}</p>}
    </Card>
  );
}
