"use client";

import { useSearchParams } from "next/navigation";
import { Download, FileSpreadsheet, FileJson } from "lucide-react";
import { useReports, useJobStatus } from "@/hooks/useCFO";
import { cn } from "@/lib/utils";
import { getDownloadUrl } from "@/lib/api/cfo";
import type { ReportMeta } from "@/types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ReportRow({ report }: { report: ReportMeta }) {
  const isExcel = report.report_format === "xlsx";
  const isPdf = report.report_format === "pdf";
  const isJson = report.report_format === "json";

  const icon = isExcel || isPdf ? (
    <FileSpreadsheet className="h-4 w-4 text-success shrink-0" aria-hidden="true" />
  ) : (
    <FileJson className="h-4 w-4 text-primary shrink-0" aria-hidden="true" />
  );

  const label = isExcel
    ? "Excel Report"
    : isPdf
    ? "PDF Report"
    : "Dashboard JSON";

  const typeBadge = `${report.report_type} · ${report.report_format.toUpperCase()}`;

  return (
    <tr className="border-b border-border/40 last:border-0 hover:bg-muted/20">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-medium">{label}</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {typeBadge}
        </span>
      </td>
      <td className="px-4 py-3 text-xs tabular text-muted-foreground whitespace-nowrap">
        {formatDate(report.created_at)}
      </td>
      <td className="px-4 py-3 text-right">
        {report.has_file ? (
          <a
            href={getDownloadUrl(report.id)}
            download
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium",
              "transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
            aria-label={`Download ${label}`}
          >
            <Download className="h-3 w-3" aria-hidden="true" />
            Download
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">No file</span>
        )}
      </td>
    </tr>
  );
}

export default function ReportsPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: reports, isLoading } = useReports(jobId);
  const { data: job } = useJobStatus(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">No job selected. Upload a document first.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-3 p-5">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const fileReports = (reports ?? []).filter((r) => r.report_format !== "json");
  const allReports = reports ?? [];

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Reports</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Download your financial analysis reports
        </p>
      </div>

      {/* Job status banner */}
      {job && (
        <div className={cn(
          "rounded-lg border px-4 py-3 text-sm",
          job.status === "completed"
            ? "border-success/20 bg-success/6 text-success"
            : job.status === "failed"
            ? "border-destructive/30 bg-destructive/8 text-destructive"
            : "border-border bg-muted/30 text-muted-foreground"
        )}>
          <span className="font-medium">{job.filename}</span>
          {" · "}
          <span className="capitalize">{job.status}</span>
          {job.completed_at && (
            <span className="ml-2 text-xs opacity-70">
              {formatDate(job.completed_at)}
            </span>
          )}
        </div>
      )}

      {/* Reports table */}
      {allReports.length > 0 ? (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h3 className="text-sm font-medium">Available Reports</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" role="table">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Report</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Type</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Generated</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Action</th>
                </tr>
              </thead>
              <tbody>
                {allReports.map((r) => (
                  <ReportRow key={r.id} report={r} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm text-muted-foreground">
            No reports yet.{" "}
            {job?.status === "completed"
              ? "Reports should appear here after analysis completes."
              : "Run analysis first to generate reports."}
          </p>
        </div>
      )}

      {/* Download all note */}
      {fileReports.length > 0 && (
        <p className="text-xs text-muted-foreground text-center">
          {fileReports.length} downloadable file{fileReports.length > 1 ? "s" : ""} available.
          Files include multi-sheet Excel reports with P&L, Cash Flow, Forecast, Tax, Anomalies, and Budget sheets.
        </p>
      )}
    </div>
  );
}
