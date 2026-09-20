"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Activity, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  fetchRunsSLO, listRuns, resumeRun,
  type AgentRun, type RunsSLO, type RunStatus,
} from "@/lib/api/runs";

const STATUS_TONE: Record<RunStatus, string> = {
  completed: "text-emerald-400",
  running: "text-blue-400",
  awaiting_review: "text-amber-400",
  failed: "text-red-400",
  halted: "text-red-400",
};

const STATUS_LABEL: Record<RunStatus, string> = {
  completed: "tamamlandı",
  running: "çalışıyor",
  awaiting_review: "onay bekliyor",
  failed: "başarısız",
  halted: "durduruldu",
};

function ms(v: number | null): string {
  if (v === null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} sn` : `${v} ms`;
}

/**
 * What the agents actually did — the run ledger, with a way back in.
 *
 * The ledger and its SLO rollup shipped as a completed phase with no frontend
 * caller, so a run that stopped halfway left a record nobody could see and a
 * resume nobody could reach.
 */
export function AgentRunLedger() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [slo, setSlo] = useState<RunsSLO | null>(null);
  const [loading, setLoading] = useState(true);
  const [resuming, setResuming] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Not an error: a user with no workspace has no runs to show, and the server
  // says so in a sentence worth passing on rather than painting red.
  const [unavailable, setUnavailable] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, s] = await Promise.all([listRuns({ limit: 10 }), fetchRunsSLO(7)]);
      setRuns(r);
      setSlo(s);
      setErr(null);
      setUnavailable(null);
    } catch (e) {
      const res = (e as { response?: { status?: number; data?: { error?: string } } })
        .response;
      if (res?.status === 400 && res.data?.error) {
        setUnavailable(res.data.error);
        setErr(null);
      } else {
        setErr("koşu kayıtları okunamadı");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const resume = useCallback(
    async (id: string) => {
      setResuming(id);
      setErr(null);
      try {
        await resumeRun(id);
        await load();
      } catch (e) {
        const detail =
          e && typeof e === "object" && "response" in e
            ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : undefined;
        setErr(detail ?? "koşu devam ettirilemedi");
      } finally {
        setResuming(null);
      }
    },
    [load],
  );

  const pipelines = Object.entries(slo?.by_pipeline ?? {});

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Activity className="h-4 w-4 text-primary" />
        Ajan koşuları
        <span className="text-xs font-normal text-muted-foreground">
          son 7 gün · {slo?.total_runs ?? 0} koşu
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          className="ml-auto h-7 px-2"
          aria-label="Yenile"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Yenile"}
        </Button>
      </div>

      {pipelines.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {pipelines.map(([name, s]) => (
            <div key={name} className="rounded-md border border-border p-2.5 text-xs">
              <div className="font-medium">{name}</div>
              <div className="mt-1 grid grid-cols-3 gap-1 text-muted-foreground">
                <span>
                  başarı{" "}
                  <span
                    className={cn(
                      "font-semibold",
                      s.success_rate !== null && s.success_rate < 0.9
                        ? "text-amber-400"
                        : "text-foreground",
                    )}
                  >
                    {s.success_rate === null ? "—" : `%${Math.round(s.success_rate * 100)}`}
                  </span>
                </span>
                <span>
                  p95 <span className="font-semibold text-foreground">{ms(s.p95_latency_ms)}</span>
                </span>
                <span>
                  koşu <span className="font-semibold text-foreground">{s.runs}</span>
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {unavailable && (
        <p className="text-xs text-muted-foreground">{unavailable}</p>
      )}

      {runs.length === 0 && !loading && !unavailable && (
        <p className="text-xs text-muted-foreground">Henüz kayıtlı koşu yok.</p>
      )}

      {runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1 pr-3 font-normal">Pipeline</th>
                <th className="py-1 pr-3 font-normal">Durum</th>
                <th className="py-1 pr-3 font-normal">Düğüm</th>
                <th className="py-1 pr-3 font-normal">Süre</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-t border-border/60">
                  <td className="py-1.5 pr-3">{r.pipeline}</td>
                  <td className={cn("py-1.5 pr-3", STATUS_TONE[r.status])}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </td>
                  <td className="py-1.5 pr-3 text-muted-foreground">
                    {r.current_node ?? "—"}
                    {r.attempt > 1 && ` (${r.attempt}. deneme)`}
                  </td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{ms(r.latency_ms)}</td>
                  <td className="py-1.5">
                    {/* Only tr_vertical can be resumed; the server says so with
                        a 400, and showing the button anyway would promise
                        something it cannot do. */}
                    {(r.status === "failed" || r.status === "halted") &&
                      r.pipeline === "tr_vertical" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 gap-1 px-2 text-xs"
                          disabled={resuming !== null}
                          onClick={() => resume(r.id)}
                        >
                          {resuming === r.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <RotateCcw className="h-3 w-3" />
                          )}
                          Devam ettir
                        </Button>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {runs.some((r) => r.error) && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            Hata mesajları
          </summary>
          <ul className="mt-1 space-y-0.5">
            {runs
              .filter((r) => r.error)
              .map((r) => (
                <li key={r.id} className="text-red-400">
                  {r.pipeline}: {r.error}
                </li>
              ))}
          </ul>
        </details>
      )}

      {err && (
        <p className="flex items-start gap-1 text-xs text-red-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {err}
        </p>
      )}
    </Card>
  );
}
