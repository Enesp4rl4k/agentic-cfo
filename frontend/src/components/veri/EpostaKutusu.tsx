"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCircle2, Copy, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  epostaAdresi, epostaAdresiYenile, gelenEpostalar, type EpostaAdresi, type GelenEposta,
} from "@/lib/api/veri";

const DURUM: Record<string, string> = {
  eklendi: "eklendi",
  onceden_alindi: "daha önce alınmış",
  secim_gerekli: "türü seçilmeli",
  taninmadi: "tanınamadı",
  reddedildi: "reddedildi",
  finansal_dosya_gerekli: "önce ekstre gerekli",
  ek_yok: "ek yok",
};

/**
 * The organisation's data mail address: set up forwarding once, and the files
 * arrive by themselves. Shows what came in and what became of each file, so
 * a person can see the automation working — or why a file was not added.
 */
export function EpostaKutusu() {
  const [adres, setAdres] = useState<EpostaAdresi | null>(null);
  const [gelen, setGelen] = useState<GelenEposta[]>([]);
  const [kopyalandi, setKopyalandi] = useState(false);
  const [onay, setOnay] = useState(false);
  const [mesgul, setMesgul] = useState(false);
  const [hata, setHata] = useState<string | null>(null);

  useEffect(() => {
    epostaAdresi()
      .then((a) => {
        setAdres(a);
        if (a.acik) gelenEpostalar().then(setGelen).catch(() => setGelen([]));
      })
      .catch((e) => setHata(e instanceof Error ? e.message : "Adres alınamadı."));
  }, []);

  async function kopyala() {
    if (!adres?.adres) return;
    try {
      await navigator.clipboard.writeText(adres.adres);
      setKopyalandi(true);
      setTimeout(() => setKopyalandi(false), 2000);
    } catch {
      setHata("Kopyalanamadı; adresi seçip kendiniz kopyalayın.");
    }
  }

  async function yenile() {
    setMesgul(true);
    try {
      setAdres(await epostaAdresiYenile());
      setOnay(false);
    } catch (e) {
      setHata(e instanceof Error ? e.message : "Adres yenilenemedi.");
    } finally {
      setMesgul(false);
    }
  }

  if (hata && !adres) return <Card className="p-4 text-xs text-red-400">{hata}</Card>;
  if (!adres) return null;

  return (
    <Card className="space-y-3 p-4">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        <Mail className="h-4 w-4" aria-hidden="true" /> E-postayla otomatik gönderin
      </p>

      {!adres.acik ? (
        <p className="text-xs text-muted-foreground">{adres.mesaj}</p>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs" title={adres.adres ?? ""}>
              {adres.adres}
            </code>
            <Button size="sm" variant="outline" onClick={kopyala} aria-label="Adresi kopyala">
              {kopyalandi
                ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
            </Button>
          </div>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {adres.nasil?.map((n) => <li key={n}>{n}</li>)}
          </ul>
          {!onay ? (
            <button type="button" onClick={() => setOnay(true)} className="text-xs text-muted-foreground underline">
              Adresi yenile
            </button>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span>Eski adrese gelen posta artık alınmaz. Emin misiniz?</span>
              <Button size="sm" variant="destructive" disabled={mesgul} onClick={yenile}>
                <RefreshCw className="mr-1 h-3 w-3" aria-hidden="true" /> Yenile
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOnay(false)}>Vazgeç</Button>
            </div>
          )}

          <div className="border-t border-border/60 pt-2">
            <p className="text-xs font-medium">Gelen e-postalar</p>
            {gelen.length === 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">Henüz e-posta gelmedi.</p>
            ) : (
              <ul className="mt-1 space-y-2">
                {gelen.map((m) => (
                  <li key={m.id} className="text-xs">
                    <p className="truncate font-medium" title={m.konu}>{m.konu || "(konusuz)"}</p>
                    <p className="text-muted-foreground">
                      {m.gonderen}{m.alindi ? ` · ${new Date(m.alindi).toLocaleString("tr-TR")}` : ""}
                    </p>
                    <ul className="mt-0.5 space-y-0.5">
                      {m.dosyalar.map((d, i) => (
                        <li key={`${d.dosya}-${i}`} className="text-muted-foreground" title={d.mesaj}>
                          {d.dosya ?? "—"}: {d.etiket ? `${d.etiket}, ` : ""}{DURUM[d.durum] ?? d.durum}
                          {d.sayfa && (
                            <Link href={d.sayfa} className="ml-1 text-primary hover:underline">aç</Link>
                          )}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {hata && adres && <p className="text-xs text-red-400">{hata}</p>}
    </Card>
  );
}
