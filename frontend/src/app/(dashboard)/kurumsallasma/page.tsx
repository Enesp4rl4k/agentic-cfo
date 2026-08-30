"use client";

export const dynamic = "force-dynamic";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, TrendingUp, ArrowRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  getInstitutionalizationIndex,
  recomputeInstitutionalizationIndex,
  getInstitutionalizationHistory,
  type InstitutionalizationSnapshot,
  type IndexHistoryPoint,
} from "@/lib/api/institutionalization";

const GRADE_TONE: Record<string, string> = {
  A: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10",
  B: "text-emerald-400 border-emerald-500/30 bg-emerald-500/5",
  C: "text-amber-400 border-amber-500/40 bg-amber-500/10",
  D: "text-orange-400 border-orange-500/40 bg-orange-500/10",
  E: "text-red-400 border-red-500/40 bg-red-500/10",
};

function barTone(score: number) {
  return score >= 70 ? "bg-emerald-500/60" : score >= 45 ? "bg-amber-500/60" : "bg-red-500/60";
}

function Sparkline({ points }: { points: IndexHistoryPoint[] }) {
  if (points.length < 2) return null;
  const vals = points.map((p) => p.overall_score);
  const min = Math.min(...vals), max = Math.max(...vals, min + 1);
  const w = 240, h = 40;
  const d = vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - ((v - min) / (max - min)) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="text-primary/70">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

export default function KurumsallasmaPage() {
  const [snap, setSnap] = useState<InstitutionalizationSnapshot | null>(null);
  const [history, setHistory] = useState<IndexHistoryPoint[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [s, h] = await Promise.all([
        getInstitutionalizationIndex(),
        getInstitutionalizationHistory(),
      ]);
      setSnap(s);
      setHistory(h);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "yüklenemedi");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const recompute = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setSnap(await recomputeInstitutionalizationIndex());
      setHistory(await getInstitutionalizationHistory());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "hesaplanamadı");
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Kurumsallaşma Endeksi</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Şirketin kurumsallaşma düzeyi — yetki delegasyonu, karar izlenebilirliği,
            insan gözetimi, süreç ritmi ve kilit-kişi riski üzerinden 0–100.
          </p>
        </div>
        <Button onClick={recompute} disabled={busy} variant="outline" className="gap-2">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Yeniden hesapla
        </Button>
      </div>

      {err && (
        <Card className="border-red-500/40 bg-red-500/5 p-3 text-sm text-red-400">{err}</Card>
      )}

      {snap && (
        <>
          <Card className="flex flex-wrap items-center gap-6 p-5">
            <div
              className={cn(
                "flex h-24 w-24 shrink-0 flex-col items-center justify-center rounded-xl border",
                GRADE_TONE[snap.grade],
              )}
            >
              <span className="text-3xl font-bold">{snap.overall_score}</span>
              <span className="text-xs">not: {snap.grade}</span>
            </div>
            <div className="min-w-[200px] flex-1 space-y-1">
              <div className="flex items-center gap-2 text-sm font-medium">
                <TrendingUp className="h-4 w-4 text-primary" /> Trend
              </div>
              <Sparkline points={history} />
              <p className="text-xs text-muted-foreground">
                {history.length} ölçüm · son:{" "}
                {snap.computed_at ? new Date(snap.computed_at).toLocaleString("tr-TR") : "—"}
              </p>
            </div>
          </Card>

          <Card className="space-y-3 p-4">
            <div className="text-sm font-medium">Boyutlar</div>
            {snap.dimensions.map((d) => (
              <div key={d.key} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span>{d.label}</span>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {d.score} · ağırlık %{Math.round(d.weight * 100)}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded bg-muted">
                  <div className={cn("h-full rounded", barTone(d.score))}
                       style={{ width: `${Math.max(3, d.score)}%` }} />
                </div>
                <p className="text-xs text-muted-foreground">{d.why}</p>
              </div>
            ))}
          </Card>

          {snap.recommendations.length > 0 && (
            <Card className="space-y-2 p-4">
              <div className="text-sm font-medium">Öncelikli adımlar</div>
              {snap.recommendations.slice(0, 6).map((r, i) => (
                <div key={i} className="flex gap-2 text-sm">
                  <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                  <span>{r.text}</span>
                </div>
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
