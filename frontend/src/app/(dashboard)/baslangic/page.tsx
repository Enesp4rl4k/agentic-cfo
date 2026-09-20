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
import { cn } from "@/lib/utils";

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

  const yukle = useCallback(async () => {
    try {
      setDurum(await baslangicDurumu());
      setHata(null);
    } catch (e) {
      setHata(e instanceof Error ? e.message : "Durum okunamadı.");
    }
  }, []);

  useEffect(() => { void yukle(); }, [yukle]);

  // An analysis in flight finishes without the person reloading the page.
  const suruyor = durum?.son_analiz?.durum === "analyzing" || durum?.son_analiz?.durum === "pending"
    || durum?.son_analiz?.durum === "ingesting";
  useEffect(() => {
    if (!suruyor) return;
    const t = setInterval(() => { void yukle(); }, 5000);
    return () => clearInterval(t);
  }, [suruyor, yukle]);

  if (hata && !durum) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-10">
        <Alert variant="destructive">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>Durum okunamadı</AlertTitle>
          <AlertDescription className="mt-2 space-y-3">
            <p>{hata}</p>
            <Button size="sm" variant="outline" onClick={() => void yukle()}>
              <RefreshCw className="h-4 w-4" /> Tekrar dene
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Başlangıç</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sistemi kullanmaya başlamak için kalan adımlar. Her adım verinizden okunur; bir adımı
          tamamladığınızda burası kendiliğinden güncellenir.
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
  const analiz = durum.son_analiz;
  const firmaTamam = durum.firma.var;
  const veriTamam = durum.veri.analiz_sayisi > 0 || durum.veri.parasut_bagli;
  const analizTamam = durum.tamamlanan_analiz > 0;
  const otomatikTamam = durum.otomatik.eposta || durum.otomatik.parasut_otomatik;

  const zorunlu = [firmaTamam, veriTamam, analizTamam];
  const tamamSayisi = zorunlu.filter(Boolean).length;
  const siradaki = zorunlu.findIndex((t) => !t); // -1 → hepsi tamam

  const d = (i: number): AdimDurumu =>
    zorunlu[i] ? "tamam" : i === siradaki ? "sirada" : "bekliyor";

  return (
    <>
      <div className="space-y-2">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">
            {tamamSayisi === 3 ? "Kurulum tamam" : `3 adımdan ${tamamSayisi}'i tamam`}
          </span>
          <span className="text-muted-foreground">{tamamSayisi}/3</span>
        </div>
        <Progress value={(tamamSayisi / 3) * 100} aria-label="Kurulum ilerlemesi" />
      </div>

      <Card className="divide-y">
        <Adim
          durumu={d(0)}
          ikon={Building2}
          baslik="Firmanızı tanımlayın"
          ozet={durum.firma.ad ?? undefined}
          aciklama="Analizler ve raporlar bu firmanın adına düzenlenir."
        >
          <FirmaFormu yenile={yenile} />
        </Adim>

        <Adim
          durumu={d(1)}
          ikon={FileSpreadsheet}
          baslik="Verilerinizi bağlayın"
          ozet={veriTamam
            ? durum.veri.parasut_bagli ? "Paraşüt bağlı" : `${durum.veri.analiz_sayisi} veri yüklendi`
            : undefined}
          aciklama="Muhasebe programınızdan ya da bankanızdan aldığınız dosyayı bırakmanız yeterli; ne olduğunu sistem anlar."
        >
          <Button asChild>
            <Link href="/baglan">Verilerimi bağla <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>

        <Adim
          durumu={d(2)}
          ikon={Clock}
          baslik="İlk analiziniz"
          ozet={analizTamam ? `${durum.tamamlanan_analiz} analiz tamamlandı` : undefined}
          aciklama="Veriniz geldiğinde analiz kendiliğinden başlar."
        >
          <AnalizAdimi analiz={analiz} veriTamam={veriTamam} yenile={yenile} />
        </Adim>

        <Adim
          durumu={otomatikTamam ? "tamam" : "sirada"}
          ikon={Repeat}
          baslik="Verilerin kendiliğinden gelmesi"
          istegeBagli
          ozet={otomatikTamam
            ? [durum.otomatik.eposta ? "E-posta adresi açık" : null,
               durum.otomatik.parasut_otomatik ? "Paraşüt otomatik" : null].filter(Boolean).join(" · ")
            : undefined}
          aciklama="Dosyaları her seferinde elle yüklemek yerine size özel e-posta adresine gönderin ya da Paraşüt bağlantınızı otomatiğe alın."
        >
          <Button variant="outline" asChild>
            <Link href="/baglan">Otomatiğe al <ArrowRight className="h-4 w-4" /></Link>
          </Button>
        </Adim>
      </Card>

      {tamamSayisi === 3 && (
        <div className="flex items-center justify-between gap-4 rounded-lg border bg-muted/30 p-4">
          <p className="text-sm text-muted-foreground">
            Kurulum tamamlandı. Şirketinizin durumu Komuta Merkezi&apos;nde.
          </p>
          <Button asChild>
            <Link href="/command-center">Komuta Merkezi <ArrowRight className="h-4 w-4" /></Link>
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
          {istegeBagli && !tamam && <Badge variant="outline">isteğe bağlı</Badge>}
          <span className="sr-only">{tamam ? "tamamlandı" : "yapılacak"}</span>
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

  async function kaydet(e: React.FormEvent) {
    e.preventDefault();
    if (ad.trim().length < 2) return;
    setKaydediliyor(true);
    setHata(null);
    try {
      await firmaOlustur(ad.trim());
      await yenile();
    } catch (err) {
      setHata(err instanceof Error ? err.message : "Firma oluşturulamadı.");
    } finally {
      setKaydediliyor(false);
    }
  }

  return (
    <form onSubmit={kaydet} className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <label htmlFor="firma-adi" className="sr-only">Firma adı</label>
        <Input
          id="firma-adi"
          value={ad}
          onChange={(e) => setAd(e.target.value)}
          placeholder="Örn. Yıldız Tekstil Ltd. Şti."
          className="w-full sm:w-72"
        />
        <Button type="submit" disabled={kaydediliyor || ad.trim().length < 2}>
          {kaydediliyor && <Loader2 className="h-4 w-4 animate-spin" />}
          Kaydet
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

  if (!analiz) {
    return (
      <p className="text-xs text-muted-foreground">
        {veriTamam ? "Analiz birazdan başlayacak." : "Önce bir veri bağlayın."}
      </p>
    );
  }

  if (analiz.onay_bekliyor) {
    const guven = analiz.guven === null ? null : Math.round(analiz.guven * 100);
    return (
      <>
        <Alert variant="warning">
          <CircleAlert className="h-4 w-4" />
          <AlertTitle>Analiz onayınızı bekliyor</AlertTitle>
          <AlertDescription className="mt-1 space-y-3">
            <p className="text-muted-foreground">
              {guven === null
                ? "Sistem bazı kalemlerden emin olamadı, bu yüzden sonucu size sormadan kullanmıyor."
                : `Sistemin bu analize güveni %${guven}. Eşik %80 olduğu için sonucu size sormadan kullanmıyor.`}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href={`/pnl?job=${analiz.id}`}>Önce sonuçlara bakayım</Link>
              </Button>
              <Button size="sm" onClick={() => setOnayAcik(true)}>Onayla ve tamamla</Button>
            </div>
            {hata && <p className="text-xs text-destructive">{hata}</p>}
          </AlertDescription>
        </Alert>

        <Dialog open={onayAcik} onOpenChange={setOnayAcik}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Analizi onaylıyor musunuz?</DialogTitle>
              <DialogDescription>
                Onayladığınızda bu analiz tamamlanmış sayılır: sonuçları şirket görünümüne işlenir ve
                diğer analizler bu veriyi kullanmaya başlar. Onayı kimin verdiği kayda geçer.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOnayAcik(false)}>Vazgeç</Button>
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
                    setHata(e instanceof Error ? e.message : "Onaylanamadı.");
                    setOnayAcik(false);
                  } finally {
                    setOnaylaniyor(false);
                  }
                }}
              >
                {onaylaniyor && <Loader2 className="h-4 w-4 animate-spin" />}
                Onayla
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
        <AlertTitle>Son analiz tamamlanamadı</AlertTitle>
        <AlertDescription className="mt-1 space-y-3">
          <p>{analiz.hata ?? "Sebep kaydedilmemiş."}</p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/baglan">Dosyayı yeniden bağla</Link>
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {analiz.dosya} işleniyor…
    </p>
  );
}
