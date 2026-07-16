"use client";

import { useSearchParams } from "next/navigation";
import { Download, FileSpreadsheet, FileText, Loader2, AlertCircle, InboxIcon } from "lucide-react";
import { useReports } from "@/hooks/useCFO";
import { getDownloadUrl } from "@/lib/api/cfo";
import { cn } from "@/lib/utils";
import type { ReportMeta } from "@/types";

// ── Format badge ──────────────────────────────────────────────────────────────

function FormatIcon({ format }: { format: string }) {
  if (format === "xlsx") {
    return <FileSpreadsheet className="h-4 w-4 text-emerald-400" aria-hidden="true" />;
  }
  return <FileText className="h-4 w-4 text-blue-400" aria-hidden="true" />;
}

function FormatBadge({ format }: { format: string }) {
  const styles: Record<string, string> = {
    xlsx: "bg-emerald-950/40 text-emerald-400 ring-emerald-500/20",
    pdf:  "bg-blue-950/40 text-blue-400 ring-blue-500/20",
    json: "bg-zinc-800 text-zinc-400 ring-zinc-600/20",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        styles[format] ?? styles.json
      )}
    >
      <FormatIcon format={format} />
      {format.toUpperCase()}
    </span>
  );
}

// ── Report row ────────────────────────────────────────────────────────────────

function ReportRow({ report }: { report: ReportMeta }) {
  const typeLabel: Record<string, string> = {
    full:     "Full Financial Report",
    pnl:      "P&L Statement",
    cashflow: "Cash Flow Statement",
    forecast: "12-Month Forecast",
  };

  return (
    <tr className="border-b border-border/40 last:border-0 transition-colors hover:bg-muted/20">
      <td className="px-4 py-3">
        <p className="text-sm font-medium">{typeLabel[report.report_type] ?? report.report_type}</p>
        <p className="mt-0.5 text-xs text-muted-foreground tabular">
          {new Date(report.created_at).toLocaleString()}
        </p>
      </td>
      <td className="px-4 py-3">
        <FormatBadge format={report.report_format} />
      </td>
      <td className="px-4 py-3 text-right">
        {report.has_file ? (
          <a
            href={getDownloadUrl(report.id)}
            download
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium",
              "text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
            )}
            aria-label={`Download ${typeLabel[report.report_type] ?? report.report_type}`}
          >
            <Download className="h-3 w-3" aria-hidden="true" />
            Download
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">JSON only</span>
        )}
      </td>
    </tr>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyReports() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-muted p-4">
        <InboxIcon className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h3 className="text-sm font-semibold">No reports yet</h3>
      <p className="mt-1 max-w-xs text-xs text-muted-foreground leading-relaxed">
        Run an analysis from the Upload page to generate P&L, cash flow, and forecast reports.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-4 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-xs font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Upload document
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");

  const { data: reports, isLoading, isError } = useReports(jobId);

  return (
    <div className="p-5">
      <div className="mb-5">
        <h1 className="text-lg font-semibold tracking-tight">Reports</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Download generated Excel and PDF reports for your analysis.
        </p>
      </div>

      {!jobId && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-md border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          No analysis selected. Open a dashboard with a job ID to see its reports.
        </div>
      )}

      {jobId && isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading reports…
        </div>
      )}

      {jobId && isError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          Failed to load reports. The analysis may still be running.
        </div>
      )}

      {jobId && !isLoading && !isError && (
        <>
          {!reports?.length ? (
            <EmptyReports />
          ) : (
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <p className="text-xs text-muted-foreground">
                  {reports.length} report{reports.length !== 1 ? "s" : ""} generated
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm" role="table" aria-label="Generated reports">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
                        Report
                      </th>
                      <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">
                        Format
                      </th>
                      <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map((r) => (
                      <ReportRow key={r.id} report={r} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
