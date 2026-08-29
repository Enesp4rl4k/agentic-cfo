"use client";

import { useState, useEffect } from "react";
import { TrendingUp, Users, Cpu, BarChart2, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BaselineSourceBadge } from "@/components/ui/baseline-source-badge";
import {
  useHeadcountCF,
  useMarketingCF,
  useTechCF,
  domainLabel,
  scoreColor,
} from "@/hooks/useSimulation";
import type {
  HeadcountMDRequest,
  MarketingMDRequest,
  TechInvestMDRequest,
  MultidomainCFResult,
  MultidomainScenario,
} from "@/lib/api/simulation";

// ── Action tabs ────────────────────────────────────────────────────────────────

type ActionTab = "headcount" | "marketing" | "tech";

const ACTION_TABS = [
  { id: "headcount" as ActionTab, label: "Personel",  icon: <Users      className="h-4 w-4" /> },
  { id: "marketing" as ActionTab, label: "Pazarlama", icon: <TrendingUp  className="h-4 w-4" /> },
  { id: "tech"      as ActionTab, label: "Teknoloji", icon: <Cpu         className="h-4 w-4" /> },
];

// ── Result card ────────────────────────────────────────────────────────────────

function ScenarioCard({ scenario }: { scenario: MultidomainScenario }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className={cn("font-semibold text-base", scoreColor(scenario.overall_score))}>
          Skor: {scenario.overall_score > 0 ? "+" : ""}{scenario.overall_score.toFixed(1)}/10
        </span>
        <span className={cn(
          "font-mono font-semibold",
          scenario.net_financial_impact_try >= 0 ? "text-emerald-400" : "text-red-400"
        )}>
          {scenario.net_financial_impact_try >= 0 ? "+" : ""}
          ₺{Math.abs(scenario.net_financial_impact_try).toLocaleString("tr-TR")}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">{scenario.recommendation}</p>

      {scenario.domain_effects.map((eff) => (
        <div
          key={eff.domain}
          className="rounded-lg border border-border bg-card/50 p-3 cursor-pointer"
          onClick={() => setExpanded(expanded === eff.domain ? null : eff.domain)}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{domainLabel(eff.domain)}</span>
              <span className={cn(
                "text-xs font-mono font-semibold",
                eff.impact_score >= 0.3 ? "text-emerald-400" :
                eff.impact_score >= 0   ? "text-yellow-400"  : "text-red-400"
              )}>
                {eff.impact_score >= 0 ? "+" : ""}{(eff.impact_score * 10).toFixed(1)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className={cn(
                "text-xs font-mono",
                eff.financial_impact_try >= 0 ? "text-emerald-400" : "text-red-400"
              )}>
                {eff.financial_impact_try >= 0 ? "+" : ""}
                ₺{Math.abs(eff.financial_impact_try).toLocaleString("tr-TR")}
              </span>
              {expanded === eff.domain
                ? <ChevronUp   className="h-3 w-3 text-muted-foreground" />
                : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
            </div>
          </div>

          {expanded === eff.domain && (
            <div className="mt-3 space-y-2 border-t border-border/50 pt-3 text-sm">
              {eff.risks.length > 0 && (
                <div>
                  <p className="text-xs text-red-400 font-medium mb-1">Riskler</p>
                  {eff.risks.map((r, i) => (
                    <p key={i} className="text-muted-foreground flex gap-2">
                      <span className="text-red-400 shrink-0">•</span>{r}
                    </p>
                  ))}
                </div>
              )}
              {eff.opportunities.length > 0 && (
                <div>
                  <p className="text-xs text-emerald-400 font-medium mb-1">Fırsatlar</p>
                  {eff.opportunities.map((o, i) => (
                    <p key={i} className="text-muted-foreground flex gap-2">
                      <span className="text-emerald-400 shrink-0">→</span>{o}
                    </p>
                  ))}
                </div>
              )}
              <p className="text-muted-foreground text-xs">
                Etki süresi: {eff.timeline_months} ay
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ResultView({ result }: { result: MultidomainCFResult }) {
  const [scenario, setScenario] = useState(1); // baz=1
  const active = result.scenarios[scenario];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <BaselineSourceBadge source={result.baseline_source} />
      </div>
      <Card className="p-4">
        <p className="text-sm text-muted-foreground">{result.executive_summary}</p>
        <p className="text-xs text-muted-foreground mt-1">
          Güven: %{Math.round(result.confidence * 100)}
        </p>
      </Card>

      <div className="flex gap-2">
        {result.scenarios.map((s, i) => (
          <button
            key={s.name}
            onClick={() => setScenario(i)}
            className={cn(
              "flex-1 rounded-lg border py-2 text-sm font-medium transition-colors",
              scenario === i
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:border-primary/50"
            )}
          >
            <div>{s.name}</div>
            <div className={cn("text-xs font-mono", scoreColor(s.overall_score))}>
              {s.overall_score > 0 ? "+" : ""}{s.overall_score.toFixed(1)}
            </div>
          </button>
        ))}
      </div>

      {active && <ScenarioCard scenario={active} />}
    </div>
  );
}

// ── Headcount form ─────────────────────────────────────────────────────────────

function HeadcountForm({ jobId, orgId }: { jobId?: string; orgId?: string }) {
  const { result, loading, error, analyze } = useHeadcountCF();
  const [delta, setDelta]           = useState(3);
  const [salary, setSalary]         = useState(45000);
  const [role, setRole]             = useState<HeadcountMDRequest["role_type"]>("general");
  const [onboarding, setOnboarding] = useState(2);
  const [horizon, setHorizon]       = useState(12);

  const handleSubmit = () => {
    analyze({ delta, avg_monthly_salary_try: salary, role_type: role,
      onboarding_months: onboarding, horizon_months: horizon, job_id: jobId, org_id: orgId });
  };

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Değişim (kişi)</label>
            <div className="flex items-center gap-3">
              <input type="range" min={-20} max={20} step={1} value={delta}
                onChange={(e) => setDelta(Number(e.target.value))} className="flex-1" />
              <span className={cn("w-12 text-right font-mono font-semibold", delta >= 0 ? "text-emerald-400" : "text-red-400")}>
                {delta > 0 ? "+" : ""}{delta}
              </span>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Ort. Maaş (₺/ay)</label>
            <div className="flex items-center gap-3">
              <input type="range" min={15000} max={200000} step={5000} value={salary}
                onChange={(e) => setSalary(Number(e.target.value))} className="flex-1" />
              <span className="w-20 text-right font-mono text-sm">₺{(salary/1000).toFixed(0)}K</span>
            </div>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">Rol Tipi</label>
          <div className="flex flex-wrap gap-2">
            {(["engineer","sales","ops","general"] as const).map((r) => (
              <button key={r} onClick={() => setRole(r)}
                className={cn("rounded-md border px-3 py-1 text-sm transition-colors",
                  role === r ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground")}>
                {r === "engineer" ? "Mühendis" : r === "sales" ? "Satış" : r === "ops" ? "Operasyon" : "Genel"}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Onboarding (ay)</label>
            <select value={onboarding} onChange={(e) => setOnboarding(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-card px-2 py-1 text-sm">
              {[1,2,3,4,6].map((v) => <option key={v} value={v}>{v} ay</option>)}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Analiz Ufku</label>
            <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}
              className="w-full rounded-md border border-border bg-card px-2 py-1 text-sm">
              {[6,12,18,24].map((v) => <option key={v} value={v}>{v} ay</option>)}
            </select>
          </div>
        </div>

        <Button onClick={handleSubmit} disabled={loading} className="w-full">
          {loading ? "Analiz ediliyor..." : "Çok Boyutlu Analizi Çalıştır"}
        </Button>
      </Card>

      {error && <p className="text-sm text-red-400 rounded-lg border border-red-500/30 bg-red-500/10 p-3">{error}</p>}
      {result && <ResultView result={result} />}
    </div>
  );
}

// ── Marketing form ─────────────────────────────────────────────────────────────

function MarketingForm({ jobId, orgId }: { jobId?: string; orgId?: string }) {
  const { result, loading, error, analyze } = useMarketingCF();
  const [budget, setBudget]   = useState(100000);
  const [roas, setRoas]       = useState(2.5);
  const [horizon, setHorizon] = useState(12);

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-4">
        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">Aylık Ek Bütçe (₺)</label>
          <div className="flex items-center gap-3">
            <input type="range" min={10000} max={1000000} step={10000} value={budget}
              onChange={(e) => setBudget(Number(e.target.value))} className="flex-1" />
            <span className="w-24 text-right font-mono text-sm">₺{(budget/1000).toFixed(0)}K</span>
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">Hedef ROAS</label>
          <div className="flex items-center gap-3">
            <input type="range" min={1} max={10} step={0.5} value={roas}
              onChange={(e) => setRoas(Number(e.target.value))} className="flex-1" />
            <span className="w-12 text-right font-mono font-semibold text-emerald-400">{roas}x</span>
          </div>
        </div>
        <Button onClick={() => analyze({ monthly_increase_try: budget, expected_roas: roas, horizon_months: horizon, job_id: jobId, org_id: orgId })}
          disabled={loading} className="w-full">
          {loading ? "Analiz ediliyor..." : "Çok Boyutlu Analizi Çalıştır"}
        </Button>
      </Card>
      {error && <p className="text-sm text-red-400 rounded-lg border border-red-500/30 bg-red-500/10 p-3">{error}</p>}
      {result && <ResultView result={result} />}
    </div>
  );
}

// ── Tech form ──────────────────────────────────────────────────────────────────

function TechForm({ jobId, orgId }: { jobId?: string; orgId?: string }) {
  const { result, loading, error, analyze } = useTechCF();
  const [invest, setInvest]     = useState(500000);
  const [ops, setOps]           = useState(20000);
  const [velocity, setVelocity] = useState(15);

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-4">
        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">One-time Yatırım (₺)</label>
          <div className="flex items-center gap-3">
            <input type="range" min={50000} max={5000000} step={50000} value={invest}
              onChange={(e) => setInvest(Number(e.target.value))} className="flex-1" />
            <span className="w-24 text-right font-mono text-sm">₺{(invest/1000).toFixed(0)}K</span>
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">Aylık Ops Artışı (₺)</label>
          <div className="flex items-center gap-3">
            <input type="range" min={0} max={100000} step={5000} value={ops}
              onChange={(e) => setOps(Number(e.target.value))} className="flex-1" />
            <span className="w-24 text-right font-mono text-sm">₺{(ops/1000).toFixed(0)}K</span>
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-sm text-muted-foreground">Beklenen Velocity Artışı</label>
          <div className="flex items-center gap-3">
            <input type="range" min={5} max={50} step={5} value={velocity}
              onChange={(e) => setVelocity(Number(e.target.value))} className="flex-1" />
            <span className="w-12 text-right font-mono font-semibold text-blue-400">%{velocity}</span>
          </div>
        </div>
        <Button onClick={() => analyze({ one_time_invest_try: invest, monthly_ops_increase_try: ops, velocity_gain_pct: velocity / 100, job_id: jobId, org_id: orgId })}
          disabled={loading} className="w-full">
          {loading ? "Analiz ediliyor..." : "Çok Boyutlu Analizi Çalıştır"}
        </Button>
      </Card>
      {error && <p className="text-sm text-red-400 rounded-lg border border-red-500/30 bg-red-500/10 p-3">{error}</p>}
      {result && <ResultView result={result} />}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────

interface CounterfactualPanelProps {
  jobId?: string;
  orgId?: string;
  className?: string;
  initialAction?: string;
}

function actionToTab(action: string): ActionTab {
  if (action === "marketing_invest" || action === "cost_cut") return "marketing";
  if (action === "tech_investment") return "tech";
  return "headcount";
}

export function CounterfactualPanel({ jobId, orgId, className, initialAction }: CounterfactualPanelProps) {
  const [tab, setTab] = useState<ActionTab>(
    initialAction ? actionToTab(initialAction) : "headcount"
  );

  useEffect(() => {
    if (initialAction) setTab(actionToTab(initialAction));
  }, [initialAction]);

  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex items-center gap-2">
        <BarChart2 className="h-5 w-5 text-blue-400" />
        <h2 className="text-lg font-semibold">Çok Boyutlu Aksiyon Analizi</h2>
      </div>
      <p className="text-sm text-muted-foreground">
        Bir aksiyon alındığında CFO, CHRO, CTO ve CMO üzerindeki birleşik etkiyi görir.
      </p>

      <div className="flex gap-2">
        {ACTION_TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
              tab === t.id ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
            )}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      {tab === "headcount" && <HeadcountForm jobId={jobId} orgId={orgId} />}
      {tab === "marketing" && <MarketingForm jobId={jobId} orgId={orgId} />}
      {tab === "tech"      && <TechForm      jobId={jobId} orgId={orgId} />}
    </div>
  );
}
