"use client";
/**
 * MultiBatchUpload — upload multiple files sequentially.
 *
 * Each file goes through validate-and-upload independently.
 * Results are shown per-file with health score + job_id.
 * On completion, navigates to the dashboard of the last successful job.
 *
 * Used as a second tab in the upload page.
 */
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Upload, CheckCircle2, XCircle, Loader2,
  FileText, Trash2, Plus, ArrowRight,
} from "lucide-react";
import { validateAndUpload, type ValidateAndUploadResult } from "@/lib/api/data_quality";
import { useCompanyContextStore } from "@/store/companyContext";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type FileStatus = "pending" | "uploading" | "done" | "error" | "blocked";

interface BatchFile {
  id: string;
  file: File;
  status: FileStatus;
  result: ValidateAndUploadResult | null;
  errorMessage: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusIcon(status: FileStatus) {
  switch (status) {
    case "uploading":
      return <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />;
    case "done":
      return <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />;
    case "error":
    case "blocked":
      return <XCircle className="h-4 w-4 text-destructive" aria-hidden="true" />;
    default:
      return <FileText className="h-4 w-4 text-muted-foreground" aria-hidden="true" />;
  }
}

function healthColor(score: number) {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-destructive";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Drop zone ─────────────────────────────────────────────────────────────────

function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const dropped = Array.from(e.dataTransfer.files as FileList).filter(
        (f: File) => f.name.match(/\.(csv|xlsx|xls|pdf)$/i)
      );
      if (dropped.length) onFiles(dropped);
    },
    [onFiles]
  );

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        dragging
          ? "border-primary bg-primary/10"
          : "border-border bg-card hover:border-primary/40"
      )}
      role="region"
      aria-label="Dosya yükleme alanı"
    >
      <div className="mb-3 rounded-full bg-muted p-3">
        <Upload className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium">Dosyaları buraya sürükleyin</p>
      <p className="mt-1 text-xs text-muted-foreground">veya</p>
      <label className="mt-2 cursor-pointer">
        <span className={cn(
          "rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5",
          "text-xs font-medium text-primary transition-colors",
          "hover:bg-primary/15"
        )}>
          Dosya Seç
        </span>
        <input
          type="file"
          multiple
          accept=".csv,.xlsx,.xls,.pdf"
          className="sr-only"
          onChange={(e) => {
            const input = e.target as HTMLInputElement;
            const files = Array.from((input.files ?? []) as FileList) as File[];
            if (files.length) onFiles(files);
            e.target.value = "";
          }}
          aria-label="Dosya seç"
        />
      </label>
      <p className="mt-3 text-[10px] text-muted-foreground">
        CSV, Excel (.xlsx/.xls), PDF banka ekstresi · Maks 10 MB/dosya
      </p>
    </div>
  );
}

// ── File row ──────────────────────────────────────────────────────────────────

function FileRow({
  item,
  onRemove,
}: {
  item: BatchFile;
  onRemove: (id: string) => void;
}) {
  const canRemove = item.status === "pending" || item.status === "error";

  return (
    <div className={cn(
      "flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors",
      item.status === "done"    ? "border-emerald-500/20 bg-emerald-500/5" :
      item.status === "error" || item.status === "blocked"
                                ? "border-destructive/20 bg-destructive/5" :
      item.status === "uploading" ? "border-primary/20 bg-primary/5" :
      "border-border bg-card"
    )}>
      {statusIcon(item.status)}

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{item.file.name}</p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{formatBytes(item.file.size)}</span>
          {item.result?.validation && (
            <span className={cn(
              "text-xs font-medium",
              healthColor(item.result.validation.health_score)
            )}>
              %{item.result.validation.health_score} kalite
            </span>
          )}
          {item.result?.job_id && (
            <span className="text-[10px] font-mono text-muted-foreground/60">
              {item.result.job_id.slice(0, 8)}
            </span>
          )}
          {item.errorMessage && (
            <span className="text-xs text-destructive">{item.errorMessage}</span>
          )}
          {item.result?.blocked_reason && (
            <span className="text-xs text-amber-400">{item.result.blocked_reason}</span>
          )}
        </div>
      </div>

      {canRemove && (
        <button
          onClick={() => onRemove(item.id)}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:text-destructive"
          aria-label={`${item.file.name} dosyasını kaldır`}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

// ── Progress summary ──────────────────────────────────────────────────────────

function ProgressSummary({
  files,
  isRunning,
}: {
  files: BatchFile[];
  isRunning: boolean;
}) {
  const done    = files.filter((f) => f.status === "done").length;
  const errors  = files.filter((f) => f.status === "error" || f.status === "blocked").length;
  const total   = files.length;
  const pct     = total === 0 ? 0 : Math.round(((done + errors) / total) * 100);

  if (!isRunning && done === 0 && errors === 0) return null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {isRunning ? "Yükleniyor…" : "Tamamlandı"}
          {" — "}
          {done}/{total} başarılı
          {errors > 0 && `, ${errors} hatalı`}
        </span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-300",
            errors > 0 && done === 0 ? "bg-destructive" : "bg-primary"
          )}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function MultiBatchUpload() {
  const router = useRouter();
  const { setActiveCFOJob } = useCompanyContextStore();
  const [files, setFiles] = useState<BatchFile[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  function addFiles(newFiles: File[]) {
    const items: BatchFile[] = newFiles.map((f) => ({
      id: `${f.name}-${f.size}-${Date.now()}-${Math.random()}`,
      file: f,
      status: "pending",
      result: null,
      errorMessage: null,
    }));
    setFiles((prev) => [...prev, ...items]);
  }

  function removeFile(id: string) {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }

  function reset() {
    setFiles([]);
  }

  async function runBatch() {
    const pending = files.filter((f) => f.status === "pending");
    if (!pending.length) return;

    setIsRunning(true);
    let lastJobId: string | null = null;

    for (const item of pending) {
      // Mark as uploading
      setFiles((prev) =>
        prev.map((f) => f.id === item.id ? { ...f, status: "uploading" } : f)
      );

      try {
        const result = await validateAndUpload(item.file, { minScore: 30 });

        if (result.job_id) {
          lastJobId = result.job_id;
          setActiveCFOJob(result.job_id);
        }

        setFiles((prev) =>
          prev.map((f) =>
            f.id === item.id
              ? {
                  ...f,
                  status: result.job_id ? "done" : "blocked",
                  result,
                  errorMessage: result.blocked_reason ?? null,
                }
              : f
          )
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Yükleme başarısız";
        setFiles((prev) =>
          prev.map((f) =>
            f.id === item.id ? { ...f, status: "error", errorMessage: msg } : f
          )
        );
      }
    }

    setIsRunning(false);

    // Navigate to dashboard of last successful job
    if (lastJobId) {
      router.push(`/?job=${lastJobId}`);
    }
  }

  const hasPending  = files.some((f) => f.status === "pending");
  const hasAny      = files.length > 0;
  const allDone     = hasAny && files.every((f) => f.status === "done" || f.status === "error" || f.status === "blocked");
  const successJobs = files.filter((f) => f.result?.job_id).map((f) => f.result!.job_id!);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h3 className="text-sm font-semibold">Toplu Dosya Yükleme</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Birden fazla dönem veya banka dosyasını aynı anda yükleyin. Her dosya ayrı ayrı analiz edilir.
        </p>
      </div>

      {/* Drop zone */}
      <DropZone onFiles={addFiles} />

      {/* File list */}
      {hasAny && (
        <div className="space-y-2">
          {files.map((item) => (
            <FileRow key={item.id} item={item} onRemove={removeFile} />
          ))}
        </div>
      )}

      {/* Progress bar */}
      <ProgressSummary files={files} isRunning={isRunning} />

      {/* Actions */}
      {hasAny && (
        <div className="flex items-center gap-3">
          {hasPending && !isRunning && (
            <button
              onClick={runBatch}
              className={cn(
                "flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5",
                "text-sm font-semibold text-primary-foreground",
                "transition-opacity hover:opacity-90",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              {files.filter((f) => f.status === "pending").length} Dosyayı Yükle
            </button>
          )}

          {isRunning && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Yükleniyor…
            </div>
          )}

          {allDone && successJobs.length > 0 && (
            <button
              onClick={() => router.push(`/?job=${successJobs[successJobs.length - 1]}`)}
              className={cn(
                "flex items-center gap-2 rounded-lg bg-emerald-500/15 px-4 py-2.5",
                "border border-emerald-500/30 text-sm font-medium text-emerald-400",
                "transition-colors hover:bg-emerald-500/20"
              )}
            >
              Dashboard&apos;a Git
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}

          <button
            onClick={reset}
            disabled={isRunning}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border border-border px-3 py-2.5",
              "text-sm text-muted-foreground transition-colors hover:text-foreground",
              "disabled:opacity-50"
            )}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Temizle
          </button>
        </div>
      )}

      {/* Success summary */}
      {allDone && successJobs.length > 0 && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
          <p className="text-sm font-medium text-emerald-400">
            {successJobs.length} dosya başarıyla yüklendi ve analiz başlatıldı.
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Son analiz ID: <code className="font-mono">{successJobs[successJobs.length - 1]}</code>
          </p>
        </div>
      )}
    </div>
  );
}
