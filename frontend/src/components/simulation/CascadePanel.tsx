"use client";

import { useState } from "react";
import { Zap, ChevronDown, ChevronUp, AlertTriangle, Info, Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useCascadeSimulator, impactColor, impactBg, domainLabel } from "@/hooks/useSimulation";
import type { CascadeSimulateRequest, TriggerType, RoleType } from "@/lib/api/simulation";

// ── Trigger form ───────────────────────────────────────────────────────────────

interface TriggerConfig {
  type: TriggerType;
  label: string;
  icon: React.ReactNode;
  color: string;
}

const TRIGGERS: TriggerConfig[] = [
  { type: "cash_crisis",         label: "Nakit Krizi",      icon: <AlertTriangle className="h-4 w-4" />, color: "text-red-400"    },
  { type: "revenue_drop",        label: "Gelir Düşüşü",     icon: <ChevronDown   className="h-4 w-4" />, color: "text-orange-400" },
  { type: "key_person_loss",     label: "Kilit Kişi Kaybı", icon: <Shield        className="h-4 w-4" />, color: "text-yellow-400" },
  { type: "market_shock",        label: "Piyasa Şoku",      icon: <Zap           className="h-4 w-4" />, color: "text-purple-400" },
];

interface CascadePanelProps {
  jobId?: string;
  orgId?: string;
  className?: string;
}

export function CascadePanel({ jobId, orgId, className }: CascadePanelProps) {
  const { result, loading, error, simulate } = useCascadeSimulator();
  const [trigger, setTrigger] = useState<TriggerType>("cash_crisis");
  const [scenario, setScenario] = useState<"iyimser" | "baz" | "kotumser">("baz");

  // Trigger-specific params
  const [runwayMonths, setRunwayMonths] = useState(2.5);
  const [dropPct, setDropPct]           = useState(30);
  const [role, setRole]                 = useState<RoleType>("cto");
  const [usdInc, setUsdInc]             = useState(30);
  const [inflation, setInflation]       = useState(50);

  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);

  const handleSimulate = () => {
    const req: CascadeSimulateRequest = {
      trigger,
      job_id: jobId,
      org_id: orgId,
    };
    if (trigger === "cash_crisis")     req.cash_crisis      = { runway_months: runwayMonths };
    if (trigger === "revenue_drop")    req.revenue_drop     = { drop_pct: dropPct / 100 };
    if (trigger === "key_person_loss") req.key_person_loss  = { role };
    if (trigger === "market_shock")    req.market_shock     = { usd_try_increase_pct: usdInc, inflation_pct: inflation };
    simulate(req);
  };

  const activeScenario = result?.scenarios.find((s) => s.name === scenario)
    ?? result?.scenarios[1] ?? null;

  return (
    <div className={cn("space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Zap className="h-5 w-5 text-orange-400" />
        <h2 className="text-lg font-semibold">Zincirleme Risk Simülasyonu</h2>
      </div>

      {/* Trigger selector */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {TRIGGERS.map((t) => (
          <button
            key={t.type}
            onClick={() => setTrigger(t.type)}
            className={cn(
              "flex items-center gap-2 rounded-lg border p-3 text-sm font-medium transition-colors",
              trigger === t.type
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-card text-muted-foreground hover:border-primary/50"
            )}
          >
            <span className={t.color}>{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Params */}
      <Card className="p-4 space-y-3">
        {trigger === "cash_crisis" && (
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Kalan Nakit Ömrü (ay)</label>
            <div className="flex items-center gap-3">
              <input
                type="range" min={0.5} max={12} step={0.5}
                value={runwayMonths}
                onChange={(e) => setRunwayMonths(Number(e.target.value))}
                className="flex-1"
              />
              <span className="w-16 text-right font-mono font-semibold text-orange-400">
                {runwayMonths} ay
              </span>
            </div>
          </div>
        )}
        {trigger === "revenue_drop" && (
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Gelir Düşüş Oranı</label>
            <div className="flex items-center gap-3">
              <input
                type="range" min={5} max={80} step={5}
                value={dropPct}
                onChange={(e) => setDropPct(Number(e.target.value))}
                className="flex-1"
              />
              <span className="w-16 text-right font-mono font-semibold text-orange-400">
                %{dropPct}
              </span>
            </div>
          </div>
        )}
        {trigger === "key_person_loss" && (
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Ayrılan Kişinin Rolü</label>
            <div className="flex flex-wrap gap-2">
              {(["cto","cfo","ceo","cmo","chro"] as RoleType[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRole(r)}
                  className={cn(
                    "rounded-md border px-3 py-1 text-sm font-medium transition-colors",
                    role === r ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
                  )}
                >
                  {r.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        )}
        {trigger === "market_shock" && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">USD/TRY Artışı (%)</label>
              <div className="flex items-center gap-2">
                <input type="range" min={5} max={200} step={5} value={usdInc}
                  onChange={(e) => setUsdInc(Number(e.target.value))} className="flex-1" />
                <span className="w-12 text-right font-mono text-orange-400">%{usdInc}</span>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-sm text-muted-foreground">Enflasyon (%)</label>
              <div className="flex items-center gap-2">
                <input type="range" min={10} max={150} step={5} value={inflation}
                  onChange={(e) => setInflation(Number(e.target.value))} className="flex-1" />
                <span className="w-12 text-right font-mono text-orange-400">%{inflation}</span>
              </div>
            </div>
          </div>
        )}

        <Button onClick={handleSimulate} disabled={loading} className="w-full">
          {loading ? "Simüle ediliyor..." : "Simülasyonu Çalıştır"}
        </Button>
      </Card>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary */}
          <Card className="p-4 space-y-2">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 mt-0.5 text-blue-400 shrink-0" />
              <p className="text-sm text-muted-foreground">{result.executive_summary}</p>
            </div>
            {result.immediate_actions.length > 0 && (
              <div className="space-y-1 pt-2 border-t border-border">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Acil Aksiyonlar</p>
                {result.immediate_actions.map((a, i) => (
                  <p key={i} className="text-sm text-foreground">{a}</p>
                ))}
              </div>
            )}
          </Card>

          {/* Scenario tabs */}
          <div className="flex gap-2">
            {result.scenarios.map((s) => (
              <button
                key={s.name}
                onClick={() => setScenario(s.name as typeof scenario)}
                className={cn(
                  "flex-1 rounded-lg border py-2 text-sm font-medium transition-colors",
                  scenario === s.name
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/50"
                )}
              >
                <div>{s.name}</div>
                <div className={cn("text-xs font-mono", s.overall_risk_score > 70 ? "text-red-400" : s.overall_risk_score > 45 ? "text-orange-400" : "text-yellow-400")}>
                  {s.overall_risk_score}/100
                </div>
              </button>
            ))}
          </div>

          {/* Domain impacts */}
          {activeScenario && (
            <div className="space-y-2">
              {activeScenario.domain_impacts.map((imp) => (
                <div
                  key={imp.domain}
                  className={cn("rounded-lg border p-3 cursor-pointer transition-colors", impactBg(imp.impact_level))}
                  onClick={() => setExpandedDomain(expandedDomain === imp.domain ? null : imp.domain)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{domainLabel(imp.domain)}</span>
                      <span className={cn("text-xs font-medium px-1.5 py-0.5 rounded", impactColor(imp.impact_level))}>
                        {imp.impact_level.toUpperCase()}
                      </span>
                      {imp.delay_months > 0 && (
                        <span className="text-xs text-muted-foreground">{imp.delay_months}ay gecikme</span>
                      )}
                    </div>
                    {expandedDomain === imp.domain ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{imp.description}</p>

                  {expandedDomain === imp.domain && (
                    <div className="mt-3 space-y-2 border-t border-border/50 pt-3">
                      {imp.mitigations.length > 0 && (
                        <div>
                          <p className="text-xs font-medium text-muted-foreground mb-1">Önerilen Aksiyonlar</p>
                          <ul className="space-y-1">
                            {imp.mitigations.map((m, i) => (
                              <li key={i} className="text-sm flex gap-2">
                                <span className="text-emerald-400 shrink-0">→</span>{m}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
