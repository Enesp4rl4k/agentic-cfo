"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle, CheckCircle2, Loader2, PlugZap, RefreshCw, TestTube2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  fetchEFaturaStatus, syncEFatura,
  type EFaturaStatus, type EFaturaSyncResult,
} from "@/lib/api/efatura";
import { POST_UPLOAD_ROUTE } from "@/lib/routes";

/** ISO date, `days` before today. */
function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

/**
 * GİB e-Fatura — the company's own invoices, from the authority.
 *
 * The endpoints have been here for a while with no surface at all, which meant
 * the one route that brings a real company's real invoices into the product
 * could not be reached from it. Everything else in the pipeline has only ever
 * seen a file somebody typed.
 */
export function EFaturaCard() {
  const router = useRouter();
  const [status, setStatus] = useState<EFaturaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<EFaturaSyncResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [startDate, setStartDate] = useState(daysAgo(30));
  const [endDate, setEndDate] = useState(daysAgo(0));

  useEffect(() => {
    fetchEFaturaStatus()
      .then(setStatus)
      .catch(() => setErr("GİB bağlantı durumu okunamadı"))
      .finally(() => setLoading(false));
  }, []);

  const sync = useCallback(async () => {
    setSyncing(true);
    setErr(null);
    setResult(null);
    try {
      const r = await syncEFatura({ start_date: startDate, end_date: endDate });
      setResult(r);
    } catch (e) {
      const detail =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { error?: string; detail?: string } } })
              .response?.data?.error ??
            (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setErr(detail ?? (e instanceof Error ? e.message : "senkronizasyon başarısız"));
    } finally {
      setSyncing(false);
    }
  }, [startDate, endDate]);

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <PlugZap className="h-4 w-4 text-primary" />
        GİB e-Fatura
        {status?.configured && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs",
              status.sandbox
                ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
            )}
          >
            {status.sandbox ? <TestTube2 className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
            {status.sandbox ? "Test ortamı" : "Üretim"}
          </span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Şirketinizin gelen ve giden faturalarını doğrudan Gelir İdaresi&apos;nden
        çeker ve CFO analizini başlatır. Gelen kutusu gider, giden kutusu gelir
        sayılır — yön GİB&apos;in kendisinden gelir, faturanın tipinden değil.
      </p>

      {loading && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> durum okunuyor…
        </p>
      )}

      {status && !status.configured && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
          <p className="text-xs text-muted-foreground">{status.message}</p>
          {status.setup_guide && (
            <dl className="space-y-0.5 text-xs">
              {Object.entries(status.setup_guide).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="font-mono text-foreground">{k}</dt>
                  <dd className="text-muted-foreground">— {v}</dd>
                </div>
              ))}
            </dl>
          )}
          {/* Named rather than linked: this is a GİB portal, and the URL the
              API reports is the one to trust, not one hardcoded here. */}
          {status.sandbox_url && (
            <p className="text-xs text-muted-foreground">
              Test ortamı: <span className="font-mono">{status.sandbox_url}</span>
            </p>
          )}
        </div>
      )}

      {status?.configured && (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Başlangıç</span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="rounded-md border bg-background px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Bitiş</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="rounded-md border bg-background px-2 py-1 text-sm"
              />
            </label>
            <Button onClick={sync} disabled={syncing} className="gap-2">
              {syncing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Faturaları çek
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            VKN {status.vkn} · {status.message}
          </p>
        </>
      )}

      {result && (
        <div className="space-y-2 rounded-md border border-border p-3 text-xs">
          {result.invoice_count === 0 ? (
            <p className="text-muted-foreground">
              {result.message ?? "Bu dönemde fatura bulunamadı."}
            </p>
          ) : (
            <>
              <p>
                <strong>{result.invoice_count}</strong> fatura ({result.inbound_count ?? 0}{" "}
                gelen, {result.outbound_count ?? 0} giden) — {result.period}
              </p>
              {/* `queued` is the honest field: a job can exist with nothing
                  running behind it, and that is exactly the failure this
                  product has shipped before. */}
              {result.queued ? (
                <p className="flex items-center gap-1 text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" /> analiz başlatıldı
                </p>
              ) : (
                <p className="flex items-center gap-1 text-amber-400">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  faturalar alındı ama analiz başlatılamadı
                </p>
              )}
              {result.job_id && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => router.push(`${POST_UPLOAD_ROUTE}?job=${result.job_id}`)}
                >
                  Analize git
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {err && (
        <p className="flex items-start gap-1 text-xs text-red-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {err}
        </p>
      )}
    </Card>
  );
}
