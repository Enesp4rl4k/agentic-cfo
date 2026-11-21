"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  ArrowRight, Building2, Check, CircleAlert, Clock, FileSpreadsheet, Landmark, Loader2, RefreshCw, Repeat,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { approveJob } from "@/lib/api/cfo";
import { baslangicDurumu, firmaOlustur, type BaslangicDurumu } from "@/lib/api/baslangic";
import { DecisionPacketPanel } from "@/components/ui/decision-packet-panel";
import { PageHead } from "@/components/brand-app/PageHead";
import { SailMark } from "@/components/brand-landing/SailMark";
import { getCashRadar, type CashRadar } from "@/lib/api/ledger";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";

type AdimDurumu = "tamam" | "sirada" | "bekliyor";

/**
 * Başlangıç — what is left to do, read from the organisation's own data.
 *
 * The first-use guide was a slideshow whose progress lived in the browser: it
 * said nothing about whether any data had arrived, and "Atla" counted as done.
 * Every line here is a fact from the database, so someone who uploaded a file
 * yesterday sees that step closed, and someone whose analysis is waiting for
 * their approval sees exactly that, with the button that clears it.
 */
export default function BaslangicPage() {
  const [durum, setDurum] = useState<BaslangicDurumu | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const { t } = useI18n();
  const bs = t.baslangic;

  // The radar's starting cash is a fact of the first completed analysis; before one, there is nothing to ask.
  const radar = useQuery({
    queryKey: ["cash-radar"],
    queryFn: getCashRadar,
    enabled: (durum?.tamamlanan_analiz ?? 0) > 0,
  });

  const yukle = useCallback(async () => {
    try {
      setDurum(await baslangicDurumu());
      setHata(null);
    } catch (e) {
      setHata(e instanceof Error ? e.message : bs.loadErrorFallback);
    }
  }, [bs]);

  useEffect(() => { void yukle(); }, [yukle]);

  // An analysis in flight finishes without the person reloading the page.
  const suruyor = durum?.son_analiz?.durum === "analyzing" || durum?.son_analiz?.durum === "pending"
    || durum?.son_analiz?.durum === "ingesting";
  useEffect(() => {
    if (!suruyor) return;
    const timer = setInterval(() => { void yukle(); }, 5000);
    return () => clearInterval(timer);
  }, [suruyor, yukle]);

  if (hata && !durum) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-10">
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>{bs.loadErrorTitle}</AlertTitle>
          <AlertDescription className="mt-2 space-y-3">
            <p>{hata}</p>
            <Button size="sm" variant="outline" onClick={() => void yukle()}>
              <RefreshCw className="h-4 w-4" /> {bs.retry}
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-8">
      <PageHead title={bs.title} subtitle={bs.subtitle} />

      {suruyor && <Hesaplaniyor />}
      {durum === null ? <Yukleniyor /> : <Adimlar durum={durum} yenile={yukle} radar={radar} />}
    </div>
  );
}

/** The route is being drawn. Only the honest part of the artboard: no invented stage list. */
function Hesaplaniyor() {
  const { t } = useI18n();
  const copy = t.baslangic.calculating;
  return (
    <section aria-live="polite" className="flex items-center gap-4 rounded-xl border border-border bg-card p-5">
      <span className="shrink-0 animate-pulse text-foreground" aria-hidden="true">
        <SailMark size={44} />
      </span>
      <div className="space-y-1">
        <h2 className="tc-display m-0 text-[24px] leading-tight">{copy.title}</h2>
        <p className="m-0 text-sm text-muted-foreground">{copy.body}</p>
      </div>
    </section>
  );
}

/** Every required step done (Hazır artboard): the first report is ready and where to read it. */
function Hazir() {
  const { t } = useI18n();
  const copy = t.baslangic.ready;
  return (
    <section className="flex flex-col items-center gap-3 rounded-xl border-[1.5px] bg-card px-6 py-8 text-center" style={{ borderColor: "var(--tc-ember)" }}>
      <span className="text-foreground" aria-hidden="true">
        <SailMark size={56} />
      </span>
      <h2 className="tc-display m-0 text-[34px] leading-tight">{copy.title}</h2>
      <p className="m-0 max-w-md text-sm text-muted-foreground">{copy.body}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        <Button asChild className="min-h-[44px]">
          <Link href="/nakit-radari">{copy.toRadar}</Link>
        </Button>
        <Button asChild variant="outline" className="min-h-[44px]">
          <Link href="/bulten">{copy.toLogbook}</Link>
        </Button>
      </div>
    </section>
  );
}

function Yukleniyor() {
  return (
    <Card className="divide-y">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-start gap-3 p-4">
          <Skeleton className="h-7 w-7 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
        </div>
      ))}
    </Card>
  );
}

type RadarDurumu = Pick<UseQueryResult<CashRadar>, "data" | "isLoading" | "isError" | "refetch">;

const ADIM_SAYISI = 4; // company, data, analysis, radar start; automation is optional

function Adimlar({
  durum, yenile, radar,
}: { durum: BaslangicDurumu; yenile: () => Promise<void>; radar: RadarDurumu }) {
  const { t } = useI18n();
  const bs = t.baslangic;
  const analiz = durum.son_analiz;
  const firmaTamam = durum.firma.var;
  const veriTamam = durum.veri.analiz_sayisi > 0 || durum.veri.parasut_bagli;
  const analizTamam = durum.tamamlanan_analiz > 0;
  const otomatikTamam = durum.otomatik.eposta || durum.otomatik.parasut_otomatik;

  const radarTamam = analizTamam && radar.data?.starting_cash_cents != null;

  const zorunlu = [firmaTamam, veriTamam, analizTamam, radarTamam];
  const tamamSayisi = zorunlu.filter(Boolean).length;
  const siradaki = zorunlu.findIndex((x) => !x); // -1 → hepsi tamam

  const d = (i: number): AdimDurumu =>
    zorunlu[i] ? "tamam" : i === siradaki ? "sirada" : "bekliyor";

  return (
    <>
      <div className="space-y-2">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">
            {tamamSayisi === ADIM_SAYISI
              ? bs.progress.complete
              : bs.progress.count.replace("{done}", String(tamamSayisi)).replace("{total}", String(ADIM_SAYISI))}
          </span>
          <span className="text-muted-foreground">{tamamSayisi}/{ADIM_SAYISI}</span>
        </div>
        <Progress value={(tamamSayisi / ADIM_SAYISI) * 100} aria-label={bs.progress.aria} />
      </div>

      {tamamSayisi === ADIM_SAYISI && <Hazir />}

      <div className="space-y-3">
        <Adim
          numara="01"
          durumu={d(0)}
          ikon={Building2}
          baslik={bs.steps.company.title}
          ozet={durum.firma.ad ?? undefined}
          aciklama={bs.steps.company.body}
        >
          <FirmaFormu yenile={yenile} />
        </Adim>

        <Adim
          numara="02"
          durumu={d(1)}
          ikon={FileSpreadsheet}
          baslik={bs.steps.data.title}
          ozet={veriTamam
            ? durum.veri.parasut_bagli
              ? bs.steps.data.parasutConnected
              : bs.steps.data.uploaded.replace("{count}", String(durum.veri.analiz_sayisi))
            : undefined}
          aciklama={bs.steps.data.body}
        >
          <Button asChild className="min-h-[44px]">
            <Link href="/baglan">{bs.steps.data.cta} <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>

        <Adim
          numara="03"
          durumu={d(2)}
          ikon={Clock}
          baslik={bs.steps.analysis.title}
          ozet={analizTamam
            ? bs.steps.analysis.done.replace("{count}", String(durum.tamamlanan_analiz))
            : undefined}
          aciklama={bs.steps.analysis.body}
        >
          <AnalizAdimi analiz={analiz} veriTamam={veriTamam} yenile={yenile} />
        </Adim>

        <Adim
          numara="04"
          durumu={d(3)}
          ikon={Landmark}
          baslik={bs.steps.radar.title}
          ozet={radarTamam && radar.data ? <RadarOzeti radar={radar.data} /> : undefined}
          aciklama={bs.steps.radar.body}
        >
          <RadarAdimi analizTamam={analizTamam} radar={radar} />
        </Adim>

        <Adim
          numara="05"
          durumu={otomatikTamam ? "tamam" : "sirada"}
          ikon={Repeat}
          baslik={bs.steps.auto.title}
          istegeBagli
          ozet={otomatikTamam
            ? [durum.otomatik.eposta ? bs.steps.auto.emailOn : null,
               durum.otomatik.parasut_otomatik ? bs.steps.auto.parasutAuto : null].filter(Boolean).join(" · ")
            : undefined}
          aciklama={bs.steps.auto.body}
        >
          <Button variant="outline" asChild className="min-h-[44px]">
            <Link href="/baglan">{bs.steps.auto.cta} <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>
      </div>
    </>
  );
}

function Adim({
  numara, durumu, ikon: Ikon, baslik, ozet, aciklama, istegeBagli, children,
}: {
  numara: string;
  durumu: AdimDurumu;
  ikon: React.ComponentType<{ className?: string }>;
  baslik: string;
  ozet?: React.ReactNode;
  aciklama: string;
  istegeBagli?: boolean;
  children: React.ReactNode;
}) {
  const tamam = durumu === "tamam";
  const acik = durumu === "sirada";
  const { t } = useI18n();
  const bs = t.baslangic;

  return (
    <section
      className={cn(
        "flex items-start gap-3 rounded-xl border bg-card p-4",
        acik ? "border-[1.5px] border-[color:var(--tc-ember)]" : "border-border",
        !acik && !tamam && "opacity-60",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
          tamam ? "border-success/40 bg-success/10 text-success" : "border-border text-muted-foreground",
        )}
        aria-hidden="true"
      >
        {tamam ? <Check className="h-4 w-4" /> : <Ikon className="h-4 w-4" />}
      </span>

      <div className="min-w-0 flex-1">
        <span className="tc-mono text-xs" style={{ color: "var(--tc-ember-text)" }}>{numara}</span>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h2 className={cn("tc-display m-0 text-[20px] leading-tight", tamam && "text-muted-foreground")}>{baslik}</h2>
          {istegeBagli && !tamam && <Badge variant="outline">{bs.optionalBadge}</Badge>}
          <span className="sr-only">{tamam ? bs.status.done : bs.status.todo}</span>
        </div>

        {tamam ? (
          ozet && <p className="mt-0.5 text-xs text-muted-foreground">{ozet}</p>
        ) : (
          <>
            <p className="mt-1 text-sm text-muted-foreground">{aciklama}</p>
            <div className="mt-3">{children}</div>
          </>
        )}
      </div>
    </section>
  );
}

/** The proven opening balance the radar starts from, as a done-step summary. */
function RadarOzeti({ radar }: { radar: CashRadar }) {
  const { t } = useI18n();
  const fmt = useCurrencyFormat();
  const { locale } = useOrgSettings();
  const tarih = radar.starting_cash_as_of
    ? new Date(`${radar.starting_cash_as_of}T00:00:00`).toLocaleDateString(locale)
    : "";
  return (
    <>
      {t.baslangic.steps.radar.known
        .replace("{amount}", fmt((radar.starting_cash_cents ?? 0) / 100))
        .replace("{date}", tarih)}
    </>
  );
}

/** Where the radar's starting cash stands: waiting, loading, unreadable, or unproven. Never a typed-in number. */
function RadarAdimi({ analizTamam, radar }: { analizTamam: boolean; radar: RadarDurumu }) {
  const { t } = useI18n();
  const copy = t.baslangic.steps.radar;

  if (!analizTamam) return <p className="text-xs text-muted-foreground">{copy.waiting}</p>;
  if (radar.isLoading) return <p className="text-xs text-muted-foreground">{copy.loading}</p>;
  if (radar.isError) {
    return (
      <Alert variant="destructive">
        <CircleAlert className="h-4 w-4" />
        <AlertTitle>{copy.loadError}</AlertTitle>
        <AlertDescription className="mt-2">
          <Button size="sm" variant="outline" onClick={() => void radar.refetch()}>
            <RefreshCw className="h-4 w-4" /> {t.baslangic.retry}
          </Button>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert variant="warning">
      <CircleAlert className="h-4 w-4" />
      <AlertTitle>{copy.unknownTitle}</AlertTitle>
      <AlertDescription className="mt-1 space-y-3">
        <p className="text-muted-foreground">{copy.unknownBody}</p>
        <Button asChild size="sm" className="min-h-[44px]">
          <Link href="/baglan">{copy.cta} <ArrowRight className="h-4 w-4" /></Link>
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function FirmaFormu({ yenile }: { yenile: () => Promise<void> }) {
  const [ad, setAd] = useState("");
  const [kaydediliyor, setKaydediliyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const { t } = useI18n();
  const bs = t.baslangic;

  async function kaydet(e: React.FormEvent) {
    e.preventDefault();
    if (ad.trim().length < 2) return;
    setKaydediliyor(true);
    setHata(null);
    try {
      await firmaOlustur(ad.trim());
      await yenile();
    } catch (err) {
      setHata(err instanceof Error ? err.message : bs.form.createError);
    } finally {
      setKaydediliyor(false);
    }
  }

  return (
    <form onSubmit={kaydet} className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <label htmlFor="firma-adi" className="sr-only">{bs.form.nameLabel}</label>
        <Input
          id="firma-adi"
          value={ad}
          onChange={(e) => setAd(e.target.value)}
          placeholder={bs.form.namePlaceholder}
          className="w-full sm:w-72"
        />
        <Button type="submit" disabled={kaydediliyor || ad.trim().length < 2}>
          {kaydediliyor && <Loader2 className="h-4 w-4 animate-spin" />}
          {bs.form.save}
        </Button>
      </div>
      {hata && <p className="text-xs text-destructive">{hata}</p>}
    </form>
  );
}

function AnalizAdimi({
  analiz, veriTamam, yenile,
}: {
  analiz: BaslangicDurumu["son_analiz"];
  veriTamam: boolean;
  yenile: () => Promise<void>;
}) {
  const [onayAcik, setOnayAcik] = useState(false);
  const [onaylaniyor, setOnaylaniyor] = useState(false);
  const [hata, setHata] = useState<string | null>(null);
  const { t } = useI18n();
  const bs = t.baslangic;

  if (!analiz) {
    return (
      <p className="text-xs text-muted-foreground">
        {veriTamam ? bs.analysis.startingSoon : bs.analysis.connectFirst}
      </p>
    );
  }

  if (analiz.onay_bekliyor) {
    const guven = analiz.guven === null ? null : Math.round(analiz.guven * 100);
    return (
      <>
        <Alert variant="warning">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>{bs.analysis.approvalTitle}</AlertTitle>
          <AlertDescription className="mt-1 space-y-3">
            <p className="text-muted-foreground">
              {guven === null
                ? bs.analysis.confidenceLow
                : bs.analysis.confidenceWith.replace("{pct}", String(guven))}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href={`/pnl?job=${analiz.id}`}>{bs.analysis.viewResults}</Link>
              </Button>
              <Button size="sm" onClick={() => setOnayAcik(true)}>{bs.analysis.approveAndFinish}</Button>
            </div>
            {hata && <p className="text-xs text-destructive">{hata}</p>}
          </AlertDescription>
        </Alert>

        {/* Imzalamadan önce: seçenekler, sonuçları, veri tazeliği, emsal. */}
        <DecisionPacketPanel jobId={analiz.id} className="mt-3" />

        <Dialog open={onayAcik} onOpenChange={setOnayAcik}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{bs.analysis.confirmTitle}</DialogTitle>
              <DialogDescription>
                {bs.analysis.confirmBody}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOnayAcik(false)}>{bs.analysis.cancel}</Button>
              <Button
                disabled={onaylaniyor}
                onClick={async () => {
                  setOnaylaniyor(true);
                  setHata(null);
                  try {
                    await approveJob(analiz.id);
                    setOnayAcik(false);
                    await yenile();
                  } catch (e) {
                    setHata(e instanceof Error ? e.message : bs.analysis.approveError);
                    setOnayAcik(false);
                  } finally {
                    setOnaylaniyor(false);
                  }
                }}
              >
                {onaylaniyor && <Loader2 className="h-4 w-4 animate-spin" />}
                {bs.analysis.approve}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </>
    );
  }

  if (analiz.durum === "failed") {
    return (
      <Alert variant="destructive">
        <CircleAlert className="h-4 w-4" />
        <AlertTitle>{bs.analysis.failedTitle}</AlertTitle>
        <AlertDescription className="mt-1 space-y-3">
          <p>{analiz.hata ?? bs.analysis.noReason}</p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/baglan">{bs.analysis.reconnect}</Link>
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {bs.analysis.processing.replace("{file}", analiz.dosya)}
    </p>
  );
}
