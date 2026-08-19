"use client";

import { useState } from "react";
import { Brain, ChevronDown, ChevronUp, Zap, TrendingUp, AlertTriangle, CheckCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { healthColor, healthBg, insightSeverityColor } from "@/lib/api/kernels";
import type { CrossDomainReport, CrossDomainInsight } from "@/lib/api/kernels";

// ── Insight Card ──────────────────────────────────────────────────────────────

function InsightCard({ insight }: { insight: CrossDomainInsight }) {
  const [open, setOpen] = useState(false);
  const typeIcon =
    insight.insight_type === "opportunity" ? <TrendingUp className="h-3 w-3" /> :
    insight.insight_type === "warning"     ? <AlertTriangle className="h-3 w-3" /> :
    <Zap className="h-3 w-3" />;

  return (
    <div
      className="rounded-lg border p-3 cursor-pointer transition-colors hover:border-primary/30"
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 flex-1 min-w-0">
          <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium shrink-0 mt-0.5", insightSeverityColor(insight.severity))}>
            {typeIcon}
            {insight.severity}
          </span>
          <p className="text-sm font-medium leading-tight">{insight.title}</p>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" /> : <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />}
      </div>

      <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{insight.description}</p>

      {open && (
        <div className="mt-3 border-t border-border/50 pt-3 space-y-2">
          {insight.evidence.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">Kanıt</p>
              {insight.evidence.map((e, i) => (
                <p key={i} className="text-xs text-muted-foreground flex gap-1.5">
                  <span className="text-blue-400 shrink-0">•</span>{e}
                </p>
              ))}
            </div>
          )}
          {insight.actions.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">Önerilen Aksiyonlar</p>
              {insight.actions.map((a, i) => (
                <p key={i} className="text-xs text-foreground flex gap-1.5">
                  <span className="text-emerald-400 shrink-0">→</span>{a}
                </p>
              ))}
            </div>
          )}
          {insight.financial_impact_try !== null && insight.financial_impact_try !== undefined && (
            <p className="text-xs text-orange-400 font-mono">
              Tahmini finansal etki: ₺{Math.abs(insight.financial_impact_try).toLocaleString("tr-TR")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Metric chip ───────────────────────────────────────────────────────────────

function MetricChip({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card/50 px-3 py-2 text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-sm font-semibold font-mono tabular-nums", color ?? "text-foreground")}>{value}</p>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

interface KernelInsightPanelProps {
  report:    CrossDomainReport | null;
  loading?:  boolean;
  error?:    string | null;
  onRefresh?: () => void;
  className?: string;
  compact?:  boolean;
}

export function KernelInsightPanel({
  report,
  loading = false,
  error = null,
  onRefresh,
  className,
  compact = false,
}: KernelInsightPanelProps) {
  const [showAll, setShowAll] = useState(false);

  if (loading) {
    return (
      <Card className={cn("p-4", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" />
          <span className="text-sm">Otomatik analiz çalışıyor...</span>
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={cn("p-4 border-red-500/20", className)}>
        <p className="text-sm text-red-400">{error}</p>
        {onRefresh && (
          <Button variant="outline" size="sm" onClick={onRefresh} className="mt-2">
            Tekrar dene
          </Button>
        )}
      </Card>
    );
  }

  if (!report) {
    return (
      <Card className={cn("p-4 border-dashed", className)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Brain className="h-4 w-4" />
            <p className="text-sm">Otomatik C-Suite analizi henüz çalıştırılmadı</p>
          </div>
          {onRefresh && (
            <Button variant="outline" size="sm" onClick={onRefresh}>
              <Brain className="h-3 w-3 mr-1" />
              Analizi Başlat
            </Button>
          )}
        </div>
      </Card>
    );
  }

  const visibleInsights = showAll ? report.insights : report.insights.slice(0, compact ? 2 : 4);

  return (
    <div className={cn("space-y-3", className)}>
      {/* Header — health score */}
      <div className={cn("rounded-xl border p-4", healthBg(report.health_label))}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <Brain className={cn("h-5 w-5", healthColor(report.health_label))} />
            <div>
              <p className="text-sm font-semibold">Şirket Sağlık Skoru</p>
              <p className="text-xs text-muted-foreground">{report.executive_summary}</p>
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className={cn("text-2xl font-bold font-mono tabular-nums", healthColor(report.health_label))}>
              {report.overall_health_score.toFixed(0)}
            </p>
            <p className="text-xs text-muted-foreground">/100</p>
          </div>
        </div>

        {/* KPI chips */}
        {!compact && (
          <div className="mt-3 grid grid-cols-4 gap-2">
            <MetricChip label="Kritik" value={report.critical_count} color={report.critical_count > 0 ? "text-red-400" : "text-emerald-400"} />
            <MetricChip label="Yüksek" value={report.high_count} color={report.high_count > 0 ? "text-orange-400" : "text-emerald-400"} />
            <MetricChip label="Insights" value={report.insights.length} />
            <MetricChip label="Hızlı Kazanım" value={report.quick_wins.length} color="text-blue-400" />
          </div>
        )}
      </div>

      {/* Cross-domain insights */}
      {report.insights.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Cross-Domain Bulgular
            </p>
            {report.insights.length > (compact ? 2 : 4) && (
              <button
                onClick={() => setShowAll(!showAll)}
                className="text-xs text-primary hover:underline"
              >
                {showAll ? "Daha az" : `+${report.insights.length - (compact ? 2 : 4)} daha`}
              </button>
            )}
          </div>
          {visibleInsights.map((ins) => (
            <InsightCard key={ins.id} insight={ins} />
          ))}
        </div>
      )}

      {/* Quick wins */}
      {!compact && report.quick_wins.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Hızlı Kazanımlar
          </p>
          {report.quick_wins.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-sm rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
              <CheckCircle className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
              <span className="text-xs">{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* Top priorities */}
      {!compact && report.top_priorities.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Öncelikli Aksiyonlar
          </p>
          {report.top_priorities.map((p, i) => (
            <p key={i} className="text-xs text-muted-foreground flex gap-2">
              <span className="text-orange-400 font-bold shrink-0">{i + 1}.</span>{p}
            </p>
          ))}
        </div>
      )}

      {onRefresh && (
        <Button variant="ghost" size="sm" onClick={onRefresh} className="w-full text-xs text-muted-foreground">
          <RefreshCw className="h-3 w-3 mr-1" />
          Yenile
        </Button>
      )}
    </div>
  );
}
