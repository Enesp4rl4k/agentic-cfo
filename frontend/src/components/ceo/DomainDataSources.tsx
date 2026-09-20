"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Cpu, Loader2, Megaphone, Plus, Settings2,
  Trash2, Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  DOMAIN_SOURCES, analyzeCSuiteFromJob, deleteDataSource, listDataSources,
  uploadDataSource,
  type AttachedSource, type DataDomain,
} from "@/lib/api/datasource";
import { listJobs, type JobSummary } from "@/lib/api/cfo";

const ICON: Record<DataDomain, typeof Cpu> = {
  cto: Cpu,
  chro: Users,
  cmo: Megaphone,
  coo: Settings2,
};

const DOMAINS = Object.keys(DOMAIN_SOURCES) as DataDomain[];

/**
 * Give the C-suite something other than the CFO's numbers to work from.
 *
 * Without a file for a domain, its kernel derives everything from the
 * financials and sector benchmarks — honestly labelled, but still an estimate
 * wearing a job title. `POST /ceo/analyze-from-job` reads whatever is attached
 * here and hands it to the domain agent instead.
 *
 * The endpoint's own docstring called this "the primary entry point for the
 * frontend wizard flow" and laid out the three steps. The wizard did not exist,
 * so neither route could be reached and every C-level stayed derived.
 */
export function DomainDataSources() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobId, setJobId] = useState("");
  const [attached, setAttached] = useState<Record<string, AttachedSource[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pickers = useRef<Record<string, HTMLInputElement | null>>({});

  useEffect(() => {
    listJobs()
      .then((all) => {
        const done = all.filter((j) => j.status === "completed");
        setJobs(done);
        if (done[0]) setJobId(done[0].job_id);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "işler alınamadı"));
  }, []);

  const refresh = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const res = await listDataSources(id);
      setAttached(res.by_domain ?? {});
    } catch {
      setAttached({});
    }
  }, []);

  useEffect(() => {
    setRan(false);
    refresh(jobId);
  }, [jobId, refresh]);

  const upload = useCallback(
    async (domain: DataDomain, sourceType: string, file: File) => {
      const key = `${domain}:${sourceType}`;
      setBusy(key);
      setErr(null);
      try {
        await uploadDataSource(jobId, domain, sourceType, file);
        await refresh(jobId);
      } catch (e) {
        const detail =
          e && typeof e === "object" && "response" in e
            ? (e as { response?: { data?: { detail?: string; error?: string } } })
                .response?.data?.detail ??
              (e as { response?: { data?: { error?: string } } }).response?.data?.error
            : undefined;
        setErr(detail ?? (e instanceof Error ? e.message : "yükleme başarısız"));
      } finally {
        setBusy(null);
      }
    },
    [jobId, refresh],
  );

  const remove = useCallback(
    async (sourceId: string) => {
      setBusy(sourceId);
      try {
        await deleteDataSource(jobId, sourceId);
        await refresh(jobId);
      } catch {
        setErr("kaynak silinemedi");
      } finally {
        setBusy(null);
      }
    },
    [jobId, refresh],
  );

  const run = useCallback(async () => {
    setRunning(true);
    setErr(null);
    try {
      await analyzeCSuiteFromJob(jobId);
      setRan(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "C-Suite analizi başarısız");
    } finally {
      setRunning(false);
    }
  }, [jobId]);

  const withData = DOMAINS.filter((d) => (attached[d] ?? []).length > 0);

  return (
    <Card className="space-y-4 p-4">
      <div>
        <div className="text-sm font-medium">C-Suite veri kaynakları</div>
        <p className="mt-1 text-xs text-muted-foreground">
          Bir alan için dosya yüklenmediğinde o rolün ajanı finansallardan ve
          sektör ortalamalarından türetir — dürüstçe etiketlenir ama yine de
          tahmindir. Dosya yükleyin, ajan gerçek veriyi okusun.
        </p>
      </div>

      <label className="block text-xs">
        <span className="mb-1 block text-muted-foreground">Analiz işi</span>
        <select
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
        >
          {jobs.length === 0 && <option value="">tamamlanmış iş yok</option>}
          {jobs.map((j) => (
            <option key={j.job_id} value={j.job_id}>
              {j.filename ?? j.job_id} — {j.job_id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        {DOMAINS.map((domain) => {
          const Icon = ICON[domain];
          const rows = attached[domain] ?? [];
          return (
            <div key={domain} className="space-y-2 rounded-md border border-border p-3">
              <div className="flex items-center gap-2 text-sm">
                <Icon className="h-4 w-4 text-primary" />
                <span className="font-medium">{DOMAIN_SOURCES[domain].label}</span>
                <span
                  className={cn(
                    "ml-auto rounded border px-1.5 py-0.5 text-[10px]",
                    rows.length
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-300",
                  )}
                >
                  {rows.length ? "gerçek veri" : "sektör varsayımı"}
                </span>
              </div>

              {rows.map((r) => (
                <div key={r.source_id} className="flex items-center gap-2 text-xs">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                  <span className="truncate">{r.filename}</span>
                  <span className="text-muted-foreground">
                    {Math.round(r.file_size_bytes / 1024)} KB
                  </span>
                  <button
                    onClick={() => remove(r.source_id)}
                    disabled={busy === r.source_id}
                    aria-label={`${r.filename} kaynağını kaldır`}
                    className="ml-auto text-muted-foreground hover:text-red-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}

              <div className="flex flex-wrap gap-1.5">
                {DOMAIN_SOURCES[domain].types.map((t) => {
                  const key = `${domain}:${t.value}`;
                  return (
                    <div key={t.value}>
                      <input
                        ref={(el) => { pickers.current[key] = el; }}
                        type="file"
                        accept=".csv,.xlsx,.xls,.json,.txt"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) upload(domain, t.value, f);
                          e.target.value = "";
                        }}
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!jobId || busy !== null}
                        onClick={() => pickers.current[key]?.click()}
                        className="h-7 gap-1 px-2 text-xs"
                      >
                        {busy === key ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Plus className="h-3 w-3" />
                        )}
                        {t.label}
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={run} disabled={!jobId || running} className="gap-2">
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          C-Suite&apos;i bu verilerle çalıştır
        </Button>
        <span className="text-xs text-muted-foreground">
          {withData.length === 0
            ? "hiçbir alanda gerçek veri yok — tüm roller finansallardan türetilecek"
            : `${withData.length}/4 alan gerçek veriyle çalışacak`}
        </span>
      </div>

      {ran && (
        <p className="flex items-center gap-1 text-xs text-emerald-400">
          <CheckCircle2 className="h-3.5 w-3.5" /> C-Suite analizi tamamlandı —
          rol sayfalarındaki provenans rozetleri güncellendi.
        </p>
      )}

      {err && (
        <p className="flex items-start gap-1 text-xs text-red-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {err}
        </p>
      )}
    </Card>
  );
}
