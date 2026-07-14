"use client";

import { useSearchParams } from "next/navigation";
import { ShieldAlert, ShieldCheck, AlertTriangle } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";
import type { AnomalyEntry, AnomalySeverity } from "@/types";

const SEVERITY_STYLES: Record<AnomalySeverity, string> = {
  high: "border-destructive/30 bg-destructive/8 text-destructive",
  medium: "border-warning/25 bg-warning/6 text-warning",
  low: "border-border bg-muted/20 text-muted-foreground",
};

const SEVERITY_BADGE: Record<AnomalySeverity, string> = {
  high: "bg-destructive/15 text-destructive",
  medium: "bg-warning/15 text-warning",
  low: "bg-muted text-muted-foreground",
};

const TYPE_LABELS: Record<string, string> = {
  outlier_amount: "Anormal Tutar",
  potential_duplicate: "Mükerrer Ödeme",
  round_number: "Yuvarlak Tutar",
  frequency_spike: "Sıklık Anomalisi",
};

function AnomalyCard({ anomaly }: { anomaly: AnomalyEntry }) {
  const severity = anomaly.severity as AnomalySeverity;
  return (
    <div className={cn("rounded-lg border px-4 py-3.5", SEVERITY_STYLES[severity])}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-xs font-medium",
                SEVERITY_BADGE[severity]
              )}
            >
              {severity.toUpperCase()}
            </span>
            <span className="text-xs font-medium">
              {TYPE_LABELS[anomaly.type] ?? anomaly.type}
            </span>
            {anomaly.vendor && (
              <span className="text-xs opacity-70 truncate">{anomaly.vendor}</span>
            )}
          </div>
          <p className="mt-1.5 text-sm leading-snug">{anomaly.detail}</p>
          <div className="mt-2 flex items-center gap-3 text-xs opacity-70">
            {anomaly.transaction_date && (
              <span>{String(anomaly.transaction_date).slice(0, 10)}</span>
            )}
            {anomaly.amount_cents != null && anomaly.amount_cents > 0 && (
              <span className="tabular font-medium">
                {formatCurrency(anomaly.amount_cents / 100)}
              </span>
            )}
            {anomaly.category && (
              <span className="rounded bg-black/20 px-1.5 py-0.5">
                {anomaly.category}
              </span>
            )}
            {anomaly.z_score != null && (
              <span>z={anomaly.z_score.toFixed(2)}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function RiskMeter({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    score >= 0.6
      ? "bg-destructive"
      : score >= 0.3
      ? "bg-warning"
      : "bg-success";

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium">Risk Skoru</p>
        <p
          className={cn(
            "text-lg font-bold tabular",
            score >= 0.6
              ? "text-destructive"
              : score >= 0.3
              ? "text-warning"
              : "text-success"
          )}
        >
          {pct}%
        </p>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {score >= 0.6
          ? "Yüksek risk — acil inceleme gerekli"
          : score >= 0.3
          ? "Orta risk — gözlem altında tutun"
          : "Düşük risk — işlemler normal görünüyor"}
      </p>
    </div>
  );
}

export default function AnomaliesPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">No job selected. Upload a document first.</p>
      </div>
    );
  }

  if (isLoading || !dashboard) {
    return (
      <div className="space-y-4 p-5">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const anomalies = dashboard.anomalies;
  if (!anomalies) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <ShieldCheck className="h-10 w-10 text-muted-foreground mb-3" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Anomali analizi bu iş için mevcut değil.</p>
      </div>
    );
  }

  const highAnomalies = anomalies.anomaly_list.filter((a) => a.severity === "high");
  const mediumAnomalies = anomalies.anomaly_list.filter((a) => a.severity === "medium");
  const lowAnomalies = anomalies.anomaly_list.filter((a) => a.severity === "low");

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Risk & Anomali Tespiti</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          İstatistiksel outlier · Mükerrer ödeme · Sıklık anomalisi
        </p>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <RiskMeter score={anomalies.risk_score} />
        <div className="rounded-lg border border-destructive/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Yüksek Risk</p>
          <p className="mt-1 text-2xl font-bold tabular text-destructive">{highAnomalies.length}</p>
        </div>
        <div className="rounded-lg border border-warning/20 bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Orta Risk</p>
          <p className="mt-1 text-2xl font-bold tabular text-warning">{mediumAnomalies.length}</p>
        </div>
        <div className="rounded-lg border border-border bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">Düşük Risk</p>
          <p className="mt-1 text-2xl font-bold tabular text-muted-foreground">{lowAnomalies.length}</p>
        </div>
      </div>

      {/* No anomalies */}
      {anomalies.anomaly_count === 0 && (
        <div className="flex flex-col items-center justify-center py-10 rounded-lg border border-success/20 bg-success/5">
          <ShieldCheck className="h-8 w-8 text-success mb-2" aria-hidden="true" />
          <p className="text-sm font-medium text-success">Anomali tespit edilmedi</p>
          <p className="mt-0.5 text-xs text-muted-foreground">Tüm işlemler normal görünüyor.</p>
        </div>
      )}

      {/* High severity */}
      {highAnomalies.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-destructive flex items-center gap-1.5">
            <ShieldAlert className="h-4 w-4" aria-hidden="true" />
            Yüksek Risk Tespitleri
          </h3>
          {highAnomalies.map((a, i) => (
            <AnomalyCard key={i} anomaly={a} />
          ))}
        </div>
      )}

      {/* Medium severity */}
      {mediumAnomalies.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-warning">Orta Risk Tespitleri</h3>
          {mediumAnomalies.map((a, i) => (
            <AnomalyCard key={i} anomaly={a} />
          ))}
        </div>
      )}

      {/* Low severity */}
      {lowAnomalies.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">Düşük Risk Tespitleri</h3>
          {lowAnomalies.map((a, i) => (
            <AnomalyCard key={i} anomaly={a} />
          ))}
        </div>
      )}

      {/* Narrative */}
      {anomalies.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">İç Denetim Özeti</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {anomalies.narrative}
          </p>
        </div>
      )}
    </div>
  );
}
