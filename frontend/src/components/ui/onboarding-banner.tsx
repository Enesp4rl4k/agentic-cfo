"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { baslangicDurumu } from "@/lib/api/baslangic";
import { STORAGE_PREFIX } from "@/lib/branding";

const STORAGE_KEY = `${STORAGE_PREFIX}_baslangic_gizle`;

/**
 * A line pointing at the setup steps, while there are any left.
 *
 * This was a five-slide wizard that opened over the app on first sight. It
 * described the product ("12 AI ajan", "ortalama süre: 45 saniye") rather than
 * the person's own setup, sent them to the old upload page, and counted a
 * click on "Atla" as progress. /baslangic holds the steps now, read from the
 * organisation's data; this only says how many are left.
 */
export function OnboardingBanner() {
  const pathname = usePathname();
  const [kalan, setKalan] = useState<number | null>(null);
  const [gizli, setGizli] = useState(true);

  useEffect(() => {
    try {
      setGizli(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      setGizli(false);
    }
  }, []);

  useEffect(() => {
    let iptal = false;
    baslangicDurumu()
      .then((d) => {
        if (iptal) return;
        const tamam = [
          d.firma.var,
          d.veri.analiz_sayisi > 0 || d.veri.parasut_bagli,
          d.tamamlanan_analiz > 0,
        ].filter(Boolean).length;
        setKalan(3 - tamam);
      })
      .catch(() => setKalan(null));
    return () => { iptal = true; };
  }, [pathname]);

  if (gizli || kalan === null || kalan === 0 || pathname === "/baslangic") return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 px-4 py-3">
      <p className="flex-1 text-sm">
        Kurulumunuzda {kalan} adım kaldı. Sistem ancak veriniz bağlandığında sizin şirketinizi anlatır.
      </p>
      <Button size="sm" asChild>
        <Link href="/baslangic">Adımları gör <ArrowRight className="h-4 w-4" /></Link>
      </Button>
      <button
        onClick={() => {
          setGizli(true);
          try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* private mode */ }
        }}
        className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Bu hatırlatmayı gizle"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
