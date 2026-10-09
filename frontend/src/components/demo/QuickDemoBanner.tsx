"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ArrowRight, FileSpreadsheet, Activity } from "lucide-react";

export function QuickDemoBanner({ accessToken }: { accessToken?: string }) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const handleStartDemo = async () => {
    setLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

      const res = await fetch(`${API_BASE}/api/v1/demo/seed`, {
        method: "POST",
        headers,
      });

      if (res.ok) {
        const json = await res.json();
        const jobId = json?.data?.job_id;
        if (jobId) {
          router.push(`/cfo?job_id=${jobId}`);
          return;
        }
      }
      router.push("/cfo");
    } catch (err) {
      console.error("Demo seed failed", err);
      router.push("/cfo");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6">
        <div className="space-y-2 max-w-xl">
          <div className="inline-flex items-center gap-2 px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wider text-muted-foreground bg-secondary/60 border border-border">
            <Activity className="h-3 w-3 text-foreground" />
            Sandbox Çevresi · Logo Tiger 2024
          </div>
          <h3 className="text-lg font-semibold tracking-tight text-foreground">
            Veri yüklemeden tam C-Suite analiz döngüsünü inceleyin
          </h3>
          <p className="text-xs text-muted-foreground leading-relaxed">
            12 aylık gerçekçi KOBİ muhasebe verileriyle anomali denetimini, nakit akışı stres testini
            ve yönetim kurulu özetini tek tıkla canlı başlatın.
          </p>

          {/* Institutional specs */}
          <div className="flex flex-wrap items-center gap-2 pt-1 font-mono text-[11px] text-muted-foreground">
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              12 Aylık P&amp;L
            </span>
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              6 Finansal Anomali
            </span>
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              Monte Carlo Runway
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center">
          <button
            onClick={handleStartDemo}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded bg-foreground px-5 py-2.5 text-xs font-semibold text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Analiz Başlatılıyor...
              </>
            ) : (
              <>
                <FileSpreadsheet className="h-3.5 w-3.5" />
                Örnek Şirket Analizini Başlat
                <ArrowRight className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
