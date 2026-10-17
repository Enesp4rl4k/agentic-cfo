"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Download,
  FileSpreadsheet,
  FileText,
  FileJson,
  Loader2,
  AlertCircle,
  InboxIcon,
  Eye,
  X,
  CheckCircle,
  Clock,
  BarChart2,
  TrendingUp,
  DollarSign,
  Layers,
} from "lucide-react";
import { useReports } from "@/hooks/useCFO";
import { downloadReport } from "@/lib/api/cfo";
import { fetchWithAuth } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import type { MessageTree } from "@/lib/i18n";
import type { ReportMeta } from "@/types";

// ── Type config ───────────────────────────────────────────────────────────────
// Icons/colours are presentation; the label/description come from the tree.

const REPORT_TYPE_META: Record<
  string,
  { icon: React.ElementType; color: string }
> = {
  full: { icon: Layers, color: "text-primary" },
  pnl: { icon: DollarSign, color: "text-emerald-400" },
  cashflow: { icon: BarChart2, color: "text-mapblue-400" },
  forecast: { icon: TrendingUp, color: "text-brass-400" },
};

function reportTypeLabel(
  type: string,
  types: MessageTree["reports"]["types"],
): string {
  return types[type as keyof typeof types]?.label ?? type;
}

// ── Format config ─────────────────────────────────────────────────────────────

const FORMAT_CONFIG: Record<
  string,
  { icon: React.ElementType; badge: string; label: string }
> = {
  xlsx: {
    icon: FileSpreadsheet,
    badge: "bg-emerald-950/40 text-emerald-400 ring-emerald-500/20",
    label: "Excel",
  },
  pdf: {
    icon: FileText,
    badge: "bg-blue-950/40 text-blue-400 ring-blue-500/20",
    label: "PDF",
  },
  json: {
    icon: FileJson,
    badge: "bg-zinc-800 text-zinc-400 ring-zinc-600/20",
    label: "JSON",
  },
};

function FormatBadge({ format }: { format: string }) {
  const cfg = FORMAT_CONFIG[format] ?? FORMAT_CONFIG.json;
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        cfg.badge
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {cfg.label}
    </span>
  );
}

// ── JSON preview modal ────────────────────────────────────────────────────────

function JsonPreviewModal({
  report,
  onClose,
}: {
  report: ReportMeta;
  onClose: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const rep = t.reports;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";

  async function load() {
    if (content || loading) return;
    setLoading(true);
    try {
      const res = await fetchWithAuth(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/reports/${report.id}/download`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setContent(JSON.stringify(json, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : rep.error);
    } finally {
      setLoading(false);
    }
  }

  // Load on mount
  if (!content && !loading && !error) void load();

  const typeLabel = reportTypeLabel(report.report_type, rep.types);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={rep.previewLabel.replace("{type}", typeLabel)}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative flex w-full max-w-2xl flex-col rounded-xl border border-border bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <FileJson className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold">{typeLabel}</p>
              <p className="text-xs text-muted-foreground">
                {rep.jsonPreview.replace("{date}", new Date(report.created_at).toLocaleString(dateTag))}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={rep.closePreview}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content */}
        <div className="max-h-[60vh] overflow-auto">
          {loading && (
            <div className="flex items-center justify-center py-16 gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {rep.loading}
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 px-5 py-8 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
          {content && (
            <pre className="p-4 font-mono text-xs leading-relaxed text-foreground/80">
              {content}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            {rep.close}
          </button>
          <a
            href="#"
            onClick={(e) => { e.preventDefault(); void downloadReport(report.id, report.report_type); }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground",
              "transition-opacity hover:opacity-90",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            <Download className="h-3 w-3" />
            {rep.downloadJson}
          </a>
        </div>
      </div>
    </div>
  );
}

// ── Report card ───────────────────────────────────────────────────────────────

function ReportCard({ report }: { report: ReportMeta }) {
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const { t, locale } = useI18n();
  const rep = t.reports;
  const dateTag = locale === "tr" ? "tr-TR" : "en-US";

  const typeMeta = REPORT_TYPE_META[report.report_type] ?? {
    icon: FileText,
    color: "text-muted-foreground",
  };
  const TypeIcon = typeMeta.icon;
  const typeInfo = rep.types[report.report_type as keyof typeof rep.types];
  const typeLabel = typeInfo?.label ?? report.report_type;
  const typeDescription = typeInfo?.description ?? "";

  async function handleDownload(e?: { preventDefault: () => void }) {
    e?.preventDefault();
    setDownloading(true);
    // A real download now, not a timer: the link could not carry the session.
    try {
      await downloadReport(report.id, report.report_type);
      setDownloaded(true);
      setTimeout(() => setDownloaded(false), 3000);
    } catch {
      setDownloaded(false);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <>
      <div className="group flex items-start gap-4 rounded-lg border border-border bg-card px-4 py-4 transition-colors hover:border-border/80 hover:bg-muted/10">
        {/* Icon */}
        <div className="mt-0.5 rounded-md border border-border bg-muted/30 p-2">
          <TypeIcon className={cn("h-4 w-4", typeMeta.color)} aria-hidden="true" />
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">{typeLabel}</p>
            <FormatBadge format={report.report_format} />
          </div>
          {typeDescription && (
            <p className="mt-0.5 text-xs text-muted-foreground">{typeDescription}</p>
          )}
          <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" aria-hidden="true" />
              {new Date(report.created_at).toLocaleString(dateTag, {
                day: "2-digit",
                month: "short",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex shrink-0 items-center gap-2">
          {/* JSON preview (only for json format or when no file) */}
          {(report.report_format === "json" || !report.has_file) && (
            <button
              onClick={() => setPreviewOpen(true)}
              className={cn(
                "flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium",
                "text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
              aria-label={rep.previewLabel.replace("{type}", typeLabel)}
            >
              <Eye className="h-3 w-3" aria-hidden="true" />
              {rep.preview}
            </button>
          )}

          {/* Download */}
          {report.has_file ? (
            <a
              href="#"
              onClick={handleDownload}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                downloaded
                  ? "border-emerald-500/40 bg-emerald-950/20 text-emerald-400"
                  : downloading
                  ? "border-border text-muted-foreground opacity-70 pointer-events-none"
                  : "border-border text-muted-foreground hover:border-primary/50 hover:text-primary"
              )}
              aria-label={`${rep.download} ${typeLabel}`}
            >
              {downloading ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              ) : downloaded ? (
                <CheckCircle className="h-3 w-3" aria-hidden="true" />
              ) : (
                <Download className="h-3 w-3" aria-hidden="true" />
              )}
              {downloaded ? rep.downloaded : downloading ? rep.preparing : rep.download}
            </a>
          ) : (
            <span className="text-xs text-muted-foreground">{rep.jsonOnly}</span>
          )}
        </div>
      </div>

      {previewOpen && (
        <JsonPreviewModal
          report={report}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyReports() {
  const { t } = useI18n();
  const rep = t.reports;
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-muted p-4">
        <InboxIcon className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h3 className="text-sm font-semibold">{rep.empty.heading}</h3>
      <p className="mt-1 max-w-xs text-xs text-muted-foreground leading-relaxed">
        {rep.empty.body}
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-4 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        {rep.empty.cta}
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const { data: reports, isLoading, isError } = useReports(jobId);
  const { t } = useI18n();
  const rep = t.reports;

  return (
    <div className="p-5">
      <div className="mb-5">
        <h1 className="text-lg font-semibold tracking-tight">{rep.title}</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {rep.subtitle}
        </p>
      </div>

      {!jobId && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-md border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {rep.noJob}
        </div>
      )}

      {jobId && isLoading && (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      )}

      {jobId && isError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {rep.loadError}
        </div>
      )}

      {jobId && !isLoading && !isError && (
        <>
          {!reports?.length ? (
            <EmptyReports />
          ) : (
            <div className="space-y-2">
              <p className="mb-3 text-xs text-muted-foreground">
                {(reports.length === 1 ? rep.generated : rep.generatedPlural).replace(
                  "{count}",
                  String(reports.length),
                )}
              </p>
              {reports.map((r) => (
                <ReportCard key={r.id} report={r} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
