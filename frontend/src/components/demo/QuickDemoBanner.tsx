"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2, ArrowRight, FileSpreadsheet, Activity } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";

export function QuickDemoBanner({ accessToken }: { accessToken?: string }) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { t } = useI18n();
  // Parent-provided token wins; otherwise fall back to the NextAuth session.
  // Without this the seed call went out unauthenticated (401) and the banner
  // silently pushed to an empty dashboard instead of starting the analysis.
  const { data: session } = useSession();
  const token = accessToken ?? session?.accessToken;

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const handleStartDemo = async () => {
    setLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;

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
            {t.demo.sandboxTag}
          </div>
          <h3 className="text-lg font-semibold tracking-tight text-foreground">
            {t.demo.bannerTitle}
          </h3>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {t.demo.bannerBody}
          </p>

          {/* Institutional specs */}
          <div className="flex flex-wrap items-center gap-2 pt-1 font-mono text-[11px] text-muted-foreground">
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              {t.demo.specPnl}
            </span>
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              {t.demo.specAnomalies}
            </span>
            <span className="rounded bg-secondary/50 px-2 py-0.5 border border-border">
              {t.demo.specMonteCarlo}
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
                {t.demo.starting}
              </>
            ) : (
              <>
                <FileSpreadsheet className="h-3.5 w-3.5" />
                {t.demo.startSample}
                <ArrowRight className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
