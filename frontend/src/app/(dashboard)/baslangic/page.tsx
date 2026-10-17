"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight, Building2, Check, CircleAlert, Clock, FileSpreadsheet, Loader2, RefreshCw, Repeat,
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
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">{bs.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {bs.subtitle}
        </p>
      </header>

      {durum === null ? <Yukleniyor /> : <Adimlar durum={durum} yenile={yukle} />}
    </div>
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

function Adimlar({ durum, yenile }: { durum: BaslangicDurumu; yenile: () => Promise<void> }) {
  const { t } = useI18n();
  const bs = t.baslangic;
  const analiz = durum.son_analiz;
  const firmaTamam = durum.firma.var;
  const veriTamam = durum.veri.analiz_sayisi > 0 || durum.veri.parasut_bagli;
  const analizTamam = durum.tamamlanan_analiz > 0;
  const otomatikTamam = durum.otomatik.eposta || durum.otomatik.parasut_otomatik;

  const zorunlu = [firmaTamam, veriTamam, analizTamam];
  const tamamSayisi = zorunlu.filter(Boolean).length;
  const siradaki = zorunlu.findIndex((x) => !x); // -1 → hepsi tamam

  const d = (i: number): AdimDurumu =>
    zorunlu[i] ? "tamam" : i === siradaki ? "sirada" : "bekliyor";

  return (
    <>
      <div className="space-y-2">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">
            {tamamSayisi === 3
              ? bs.progress.complete
              : bs.progress.count.replace("{done}", String(tamamSayisi))}
          </span>
          <span className="text-muted-foreground">{tamamSayisi}/3</span>
        </div>
        <Progress value={(tamamSayisi / 3) * 100} aria-label={bs.progress.aria} />
      </div>

      <Card className="divide-y">
        <Adim
          durumu={d(0)}
          ikon={Building2}
          baslik={bs.steps.company.title}
          ozet={durum.firma.ad ?? undefined}
          aciklama={bs.steps.company.body}
        >
          <FirmaFormu yenile={yenile} />
        </Adim>

        <Adim
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
          <Button asChild>
            <Link href="/baglan">{bs.steps.data.cta} <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>

        <Adim
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
          <Button variant="outline" asChild>
            <Link href="/baglan">{bs.steps.auto.cta} <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>
      </Card>

      {tamamSayisi === 3 && (
        <div className="flex items-center justify-between gap-4 rounded-lg border bg-muted/30 p-4">
          <p className="text-sm text-muted-foreground">
            {bs.doneBanner.body}
          </p>
          <Button asChild>
            <Link href="/command-center">{bs.doneBanner.cta} <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </div>
      )}
    </>
  );
}

function Adim({
  durumu, ikon: Ikon, baslik, ozet, aciklama, istegeBagli, children,
}: {
  durumu: AdimDurumu;
  ikon: React.ComponentType<{ className?: string }>;
  baslik: string;
  ozet?: string;
  aciklama: string;
  istegeBagli?: boolean;
  children: React.ReactNode;
}) {
  const tamam = durumu === "tamam";
  const acik = durumu === "sirada";
  const { t } = useI18n();
  const bs = t.baslangic;

  return (
    <section className={cn("flex items-start gap-3 p-4", !acik && !tamam && "opacity-60")}>
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
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h2 className={cn("text-sm font-medium", tamam && "text-muted-foreground")}>{baslik}</h2>
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
