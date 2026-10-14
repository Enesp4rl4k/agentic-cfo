"use client";

import { useState } from "react";
import { Shield, AlertTriangle, Zap, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { KRIGauge, KRIList, RiskPostureBadge } from "@/components/risk/KRIGauge";
import { useRiskCascadeFromJob, useRiskCascadeFromOrg } from "@/hooks/useRisk";
import { postureBg, postureColor } from "@/lib/api/risk";
import { useCompanyContextStore } from "@/store/companyContext";
import { DomainPanel } from "@/components/domains/DomainPanel";
import { useI18n } from "@/hooks/useI18n";
import type { RiskCascadeReport, KRI } from "@/lib/api/risk";

// ── Risk Matrix (ısı haritası) ────────────────────────────────────────────────

const MATRIX_COLORS = [
  ["bg-emerald-500/20", "bg-emerald-500/20", "bg-yellow-500/20",  "bg-yellow-500/20",  "bg-orange-500/20"],
  ["bg-emerald-500/20", "bg-yellow-500/20",  "bg-yellow-500/20",  "bg-orange-500/20",  "bg-red-500/20"],
  ["bg-yellow-500/20",  "bg-yellow-500/20",  "bg-orange-500/20",  "bg-red-500/20",     "bg-red-500/20"],
  ["bg-yellow-500/20",  "bg-orange-500/20",  "bg-red-500/20",     "bg-red-500/30",     "bg-red-500/40"],
  ["bg-orange-500/20",  "bg-red-500/20",     "bg-red-500/30",     "bg-red-500/40",     "bg-red-500/50"],
];

interface RiskItem { name: string; likelihood: number; impact: number; status: string; }

function buildMatrixItems(kris: KRI[]): RiskItem[] {
  return kris
    .filter((k) => k.status !== "green")
    .slice(0, 8)
    .map((k) => {
      // Placement follows the measured status only; no trend is measured from one period.
      const likelihood = k.status === "red" ? 4 : 2;
      const impact     = k.cascade_trigger ? 4 : k.status === "red" ? 3 : 2;
      return { name: k.name, likelihood, impact, status: k.status };
    });
}

function RiskMatrix({ kris }: { kris: KRI[] }) {
  const { t } = useI18n();
  const matrix = t.risk.matrix;
  const LIKELIHOOD = Object.values(matrix.likelihood);
  const IMPACT = Object.values(matrix.impact);
  const items = buildMatrixItems(kris);
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              <th className="w-24 text-left p-1 text-muted-foreground">{matrix.axis}</th>
              {IMPACT.map((imp) => (
                <th key={imp} className="p-1 text-center text-muted-foreground font-normal w-16">{imp}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LIKELIHOOD.slice().reverse().map((lik, ri) => {
              const row = LIKELIHOOD.length - 1 - ri;
              return (
                <tr key={lik}>
                  <td className="p-1 text-muted-foreground text-xs">{lik}</td>
                  {IMPACT.map((_, col) => {
                    const cell = items.filter(
                      (i) => i.likelihood === row && i.impact === col
                    );
                    return (
                      <td
                        key={col}
                        className={cn(
                          "border border-border/30 p-1 text-center h-10 align-middle",
                          MATRIX_COLORS[row]?.[col] ?? "bg-muted/20"
                        )}
                      >
                        {cell.map((c) => (
                          <span
                            key={c.name}
                            title={c.name}
                            className={cn(
                              "inline-block w-2 h-2 rounded-full mx-0.5",
                              c.status === "red" ? "bg-red-500" : "bg-yellow-500"
                            )}
                          />
                        ))}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {items.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {items.map((i) => (
            <span key={i.name} className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className={cn("inline-block w-2 h-2 rounded-full", i.status === "red" ? "bg-red-500" : "bg-yellow-500")} />
              {i.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Cascade Link kartı ────────────────────────────────────────────────────────

function CascadeLinkCard({ link }: { link: RiskCascadeReport["cascade_links"][0] }) {
  const [open, setOpen] = useState(false);
  const base = link.cascade_result
    ? (link.cascade_result as Record<string, unknown[]>)?.scenarios?.find(
        (s: unknown) => (s as Record<string, string>).name === "baz"
      )
    : null;
  const riskScore = base ? (base as Record<string, number>).overall_risk_score : null;

  return (
    <div
      className={cn(
        "rounded-lg border p-3 cursor-pointer transition-colors",
        link.kri_status === "red"
          ? "border-red-500/30 bg-red-500/5"
          : "border-yellow-500/30 bg-yellow-500/5"
      )}
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={cn("text-xs font-medium px-1.5 py-0.5 rounded",
            link.kri_status === "red" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"
          )}>
            {link.kri_status.toUpperCase()}
          </span>
          <span className="text-sm font-medium">{link.kri_name}</span>
          <span className="text-xs text-muted-foreground">
            {link.kri_value} {link.kri_unit}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {riskScore !== null && (
            <span className={cn("text-xs font-mono font-semibold",
              riskScore > 70 ? "text-red-400" : riskScore > 45 ? "text-orange-400" : "text-yellow-400"
            )}>
              {riskScore.toFixed(0)}/100
            </span>
          )}
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </div>

      {open && link.cascade_result && (
        <div className="mt-3 border-t border-border/50 pt-3 space-y-2">
          <p className="text-xs text-muted-foreground">
            {(link.cascade_result as Record<string, string>).executive_summary}
          </p>
          {((link.cascade_result as Record<string, string[]>).immediate_actions || []).map((a: string, i: number) => (
            <p key={i} className="text-xs flex gap-1.5">
              <span className="text-emerald-400 shrink-0">→</span>{a}
            </p>
          ))}
        </div>
      )}
      {link.cascade_error && (
        <p className="mt-1 text-xs text-red-400">{link.cascade_error}</p>
      )}
    </div>
  );
}

// ── Ana sayfa ──────────────────────────────────────────────────────────────────

export default function RiskPage() {
  const { activeCFOJobId, orgId } = useCompanyContextStore();
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<"overview" | "matrix" | "cascade" | "categories">("overview");

  const fromJob = useRiskCascadeFromJob();
  const fromOrg = useRiskCascadeFromOrg();

  const active = orgId ? fromOrg : fromJob;
  const report: RiskCascadeReport | null = active.result;

  const handleLoad = () => {
    if (orgId) {
      fromOrg.load({ orgId, maxCascades: 5 });
    } else if (activeCFOJobId) {
      fromJob.load({ jobId: activeCFOJobId, maxCascades: 5 });
    }
  };

  const posture = report?.kri_posture;
  const allKris = posture?.all_kris ?? [];

  const TABS = [
    { id: "overview"  as const, label: t.risk.tabs.overview },
    { id: "matrix"    as const, label: t.risk.tabs.matrix },
    { id: "cascade"   as const, label: t.risk.tabs.cascade.replace("{count}", String(report?.total_cascades ?? 0)) },
    { id: "categories" as const, label: t.risk.tabs.categories },
  ];

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">{t.risk.title}</h1>
        </div>
        <Button onClick={handleLoad} disabled={active.loading} size="sm" variant="outline">
          <RefreshCw className={cn("h-4 w-4 mr-2", active.loading && "animate-spin")} />
          {active.loading ? t.risk.loading : t.risk.run}
        </Button>
      </div>

      {/* No data state */}
      {!report && !active.loading && (
        <Card className="p-8 text-center space-y-3">
          <Shield className="h-10 w-10 text-muted-foreground mx-auto" />
          <p className="font-medium">{t.risk.empty.heading}</p>
          <p className="text-sm text-muted-foreground">
            {activeCFOJobId || orgId
              ? t.risk.empty.bodyWithData
              : t.risk.empty.bodyNoData}
          </p>
          {(activeCFOJobId || orgId) && (
            <Button onClick={handleLoad} className="mt-2">
              {t.risk.empty.cta}
            </Button>
          )}
        </Card>
      )}

      {/* Error */}
      {active.error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {active.error}
        </div>
      )}

      {/* Results */}
      {report && posture && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Card className={cn("p-4 border", postureBg(posture.posture as never))}>
              <p className="text-xs text-muted-foreground mb-1">{t.risk.kpi.posture}</p>
              <p className={cn("text-lg font-bold", postureColor(posture.posture as never))}>
                {posture.posture_tr}
              </p>
              <p className="text-xs font-mono text-muted-foreground">
                {posture.kri_score === null ? t.risk.kpi.noMeasuredKri : `${posture.kri_score}/10`}
              </p>
            </Card>
            <Card className="p-4 border border-red-500/20">
              <p className="text-xs text-muted-foreground mb-1">{t.risk.kpi.red}</p>
              <p className="text-2xl font-bold text-red-400 tabular-nums">{posture.counts.red}</p>
              <p className="text-xs text-muted-foreground">{t.risk.kpi.totalCount.replace("{count}", String(posture.counts.total))}</p>
            </Card>
            <Card className="p-4 border border-yellow-500/20">
              <p className="text-xs text-muted-foreground mb-1">{t.risk.kpi.amber}</p>
              <p className="text-2xl font-bold text-yellow-400 tabular-nums">{posture.counts.amber}</p>
              <p className="text-xs text-muted-foreground">{t.risk.kpi.greenCount.replace("{count}", String(posture.counts.green))}</p>
            </Card>
            <Card className="p-4 border border-orange-500/20">
              <p className="text-xs text-muted-foreground mb-1">{t.risk.kpi.cascade}</p>
              <p className="text-2xl font-bold text-orange-400 tabular-nums">{report.total_cascades}</p>
              <p className="text-xs text-muted-foreground">{t.risk.kpi.domainsAffected.replace("{count}", String(report.domains_at_risk.length))}</p>
            </Card>
          </div>

          {posture.sources.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t.risk.kpi.sources.replace("{sources}", posture.sources.join(" · "))}
            </p>
          )}

          {posture.posture === "no_data" && (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {t.risk.noDataBody}
              </p>
              <DomainPanel alan="risk" jobId={activeCFOJobId} />
            </div>
          )}

          {/* Summary */}
          <Card className="p-4">
            <div className="flex gap-2">
              <AlertTriangle className="h-4 w-4 text-orange-400 shrink-0 mt-0.5" />
              <p className="text-sm text-muted-foreground">{report.cascade_summary}</p>
            </div>
          </Card>

          {/* Tabs */}
          <div className="flex gap-2 border-b border-border pb-0">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={cn(
                  "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                  activeTab === t.id
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="pt-2">
            {activeTab === "overview" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-3">
                  <KRIList kris={posture.red_kris}   title={t.risk.lists.red} />
                  <KRIList kris={posture.amber_kris}  title={t.risk.lists.amber} compact />
                </div>
                <div className="space-y-3">
                  <KRIList kris={posture.cascade_ready} title={t.risk.lists.cascadeReady} compact />
                </div>
              </div>
            )}

            {activeTab === "matrix" && (
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {t.risk.matrix.legend}
                </p>
                <RiskMatrix kris={allKris} />
              </div>
            )}

            {activeTab === "cascade" && (
              <div className="space-y-3">
                {report.cascade_links.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">
                    {t.risk.cascadeEmpty}
                  </p>
                ) : (
                  report.cascade_links.map((link, i) => (
                    <CascadeLinkCard key={i} link={link} />
                  ))
                )}
              </div>
            )}

            {activeTab === "categories" && (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(posture.by_category)
                  .filter(([, kris]) => kris.length > 0)
                  .map(([cat, kris]) => (
                    <Card key={cat} className="p-4 space-y-3">
                      <h3 className="text-sm font-semibold">
                        {t.risk.categories[cat as keyof typeof t.risk.categories] ?? cat}
                      </h3>
                      <KRIList kris={kris} compact />
                    </Card>
                  ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
