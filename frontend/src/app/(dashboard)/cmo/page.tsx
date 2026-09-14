"use client";

import { useEffect, useState } from "react";
import {
  TrendingUp, Target, Users, BarChart2,
  AlertTriangle, Megaphone, RefreshCw,
} from "lucide-react";
import { useAgentJob, type AgentJobRequest } from "@/hooks/useAgentJob";
import { AgentJobPanel } from "@/components/ui/agent-job-panel";
import { AgentCsvInput } from "@/components/ui/agent-csv-input";
import { apiClient } from "@/lib/api/client";
import { useCompanyContextStore } from "@/store/companyContext";

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// ── API (legacy — kept for reference, no longer called directly) ───────────────

async function runCMOAnalysis(body: CMOFormData) {
  const res = await apiClient.post<{ data: CMOResult; error: string | null }>(
    "/cmo/analyze",
    body
  );
  return res.data.data;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface CampaignData {
  total_spend_cents: number;
  total_revenue_cents: number;
  total_conversions: number;
  overall_roas: number;
  overall_cac_cents: number;
  by_channel: Record<string, {
    spend_cents: number; revenue_cents: number; roas: number;
    cac_cents: number; conversions: number; ctr: number;
  }>;
  top_campaigns: Array<{
    name: string; channel: string; spend_cents: number;
    revenue_cents: number; roas: number; cac_cents: number; status: string;
  }>;
  underperforming: Array<{ name: string; channel: string; spend_cents: number; roas: number; reason: string }>;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface FunnelData {
  total_leads: number;
  mql_count: number;
  sql_count: number;
  won_count: number;
  lead_to_mql_rate: number;
  mql_to_sql_rate: number;
  sql_to_won_rate: number;
  overall_conversion_rate: number;
  avg_cycle_days: number;
  by_source: Record<string, { leads: number; mqls: number; sqls: number; won: number; conversion_rate: number }>;
  bottleneck_stage: string;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface CohortData {
  cohorts_analyzed: number;
  avg_retention_30d: number;
  avg_retention_90d: number;
  avg_ltv_cents: number;
  avg_cac_cents: number;
  ltv_cac_ratio: number;
  churn_rate: number;
  best_cohort: { period: string; retention_30d: number; ltv_cents: number } | null;
  worst_cohort: { period: string; retention_30d: number; ltv_cents: number } | null;
  retention_trend: "improving" | "stable" | "degrading";
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface CMOSummary {
  overall_marketing_score: number;
  growth_efficiency_score: number;
  component_scores: Record<string, number>;
  top_risks: Array<{ domain: string; severity: string; message: string }>;
  quick_wins: Array<{ action: string; estimated_impact: string; effort: string }>;
  narrative: string;
}

interface CMOResult {
  job_id: string;
  campaigns?: CampaignData;
  funnel?: FunnelData;
  cohorts?: CohortData;
  cmo_summary?: CMOSummary;
  error?: string;
}

interface CMOFormData {
  company_name?: string;
  period?: string;
  campaign_csv?: string;
  funnel_csv?: string;
  cohort_csv?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: unknown): string {
  if (n === null || n === undefined) return "—";
  if (typeof n === "number") {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(n);
  }
  return String(n);
}

function fmtCents(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format(cents / 100);
}

function fmtPct(val: number): string {
  return `${(val * 100).toFixed(1)}%`;
}

function scoreColor(score: number): string {
  if (score <= 3) return "text-green-400";
  if (score <= 6) return "text-yellow-400";
  return "text-red-400";
}

function severityColor(s: string) {
  if (s === "critical") return "bg-red-500/20 text-red-400 border border-red-500/30";
  if (s === "high")     return "bg-orange-500/20 text-orange-400 border border-orange-500/30";
  if (s === "medium")   return "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30";
  return "bg-blue-500/20 text-blue-400 border border-blue-500/30";
}

function statusColor(s: string) {
  if (s === "strong")        return "text-green-400";
  if (s === "good")          return "text-blue-400";
  if (s === "break_even")    return "text-yellow-400";
  return "text-red-400";
}

function trendIcon(trend: string) {
  if (trend === "improving") return <span className="text-green-400">↑ Improving</span>;
  if (trend === "degrading") return <span className="text-red-400">↓ Degrading</span>;
  return <span className="text-muted-foreground">→ Stable</span>;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionCard({
  title, icon, children,
}: {
  title: string; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="font-semibold text-foreground">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function KPIRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-border/50 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  );
}

function AlertList({ alerts }: { alerts: Array<{ level: string; message: string }> }) {
  if (!alerts.length) return null;
  return (
    <div className="space-y-2">
      {alerts.map((a, i) => (
        <div key={i} className={`rounded px-3 py-2 text-xs ${severityColor(a.level)}`}>
          <span className="font-semibold uppercase mr-2">{a.level}</span>
          {a.message}
        </div>
      ))}
    </div>
  );
}

function CampaignSection({ data }: { data: CampaignData }) {
  return (
    <SectionCard title="Campaign Performance" icon={<Megaphone className="h-4 w-4 text-primary" />}>
      <div className="space-y-1">
        <KPIRow label="Total Spend" value={fmtCents(data.total_spend_cents)} />
        <KPIRow label="Total Revenue" value={fmtCents(data.total_revenue_cents)} />
        <KPIRow label="Overall ROAS" value={<span className={data.overall_roas >= 2 ? "text-green-400" : "text-red-400"}>{fmt(data.overall_roas)}x</span>} />
        <KPIRow label="Avg CAC" value={fmtCents(data.overall_cac_cents)} />
        <KPIRow label="Total Conversions" value={fmt(data.total_conversions)} />
      </div>

      {Object.keys(data.by_channel).length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-2 font-medium">By Channel</p>
          <div className="space-y-1">
            {Object.entries(data.by_channel).map(([ch, d]) => (
              <div key={ch} className="flex justify-between text-xs py-1 border-b border-border/30 last:border-0">
                <span className="text-muted-foreground capitalize">{ch}</span>
                <span className="tabular-nums">
                  {fmtCents(d.spend_cents)} spend · <span className={d.roas >= 2 ? "text-green-400" : "text-yellow-400"}>{d.roas}x ROAS</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.top_campaigns.length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-2 font-medium">Top Campaigns</p>
          <div className="space-y-1">
            {data.top_campaigns.map((c, i) => (
              <div key={i} className="flex justify-between text-xs py-1">
                <span className="truncate max-w-[60%] text-muted-foreground">{c.name}</span>
                <span className={`font-medium tabular-nums ${statusColor(c.status)}`}>{c.roas}x</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.narrative && (
        <p className="text-xs text-muted-foreground italic border-t border-border/50 pt-3">{data.narrative}</p>
      )}
      <AlertList alerts={data.alerts} />
    </SectionCard>
  );
}

function FunnelSection({ data }: { data: FunnelData }) {
  const stages = [
    { label: "Leads", count: data.total_leads, rate: null },
    { label: "MQLs", count: data.mql_count, rate: data.lead_to_mql_rate },
    { label: "SQLs", count: data.sql_count, rate: data.mql_to_sql_rate },
    { label: "Won", count: data.won_count, rate: data.sql_to_won_rate },
  ];

  return (
    <SectionCard title="Lead Funnel" icon={<Target className="h-4 w-4 text-accent" />}>
      <div className="space-y-2">
        {stages.map((s, i) => (
          <div key={i} className="flex items-center gap-3">
            <div
              className="h-8 bg-primary/20 rounded flex items-center justify-center text-xs font-medium tabular-nums text-primary min-w-[48px]"
              style={{ width: `${Math.max(20, (s.count / data.total_leads) * 100)}%` }}
            >
              {fmt(s.count)}
            </div>
            <div className="text-xs text-muted-foreground">
              {s.label}
              {s.rate !== null && (
                <span className={`ml-2 font-medium ${s.rate >= 0.1 ? "text-green-400" : "text-red-400"}`}>
                  ↓ {fmtPct(s.rate)}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-1 pt-2 border-t border-border/50">
        <KPIRow label="Overall Conversion" value={<span className={data.overall_conversion_rate >= 0.05 ? "text-green-400" : "text-red-400"}>{fmtPct(data.overall_conversion_rate)}</span>} />
        <KPIRow label="Avg Sales Cycle" value={`${fmt(data.avg_cycle_days)} days`} />
        <KPIRow label="Bottleneck Stage" value={<span className="text-yellow-400">{data.bottleneck_stage.replace(/_/g, " ")}</span>} />
      </div>

      {Object.keys(data.by_source).length > 0 && (
        <div>
          <p className="text-xs text-muted-foreground mb-2 font-medium">By Source</p>
          {Object.entries(data.by_source)
            .sort((a, b) => b[1].conversion_rate - a[1].conversion_rate)
            .slice(0, 5)
            .map(([src, d]) => (
              <div key={src} className="flex justify-between text-xs py-1 border-b border-border/30 last:border-0">
                <span className="text-muted-foreground capitalize">{src}</span>
                <span className="tabular-nums">{d.leads} leads → {d.won} won ({fmtPct(d.conversion_rate)})</span>
              </div>
            ))}
        </div>
      )}

      {data.narrative && (
        <p className="text-xs text-muted-foreground italic border-t border-border/50 pt-3">{data.narrative}</p>
      )}
      <AlertList alerts={data.alerts} />
    </SectionCard>
  );
}

function CohortSection({ data }: { data: CohortData }) {
  return (
    <SectionCard title="Customer Retention & LTV" icon={<Users className="h-4 w-4 text-yellow-400" />}>
      <div className="space-y-1">
        <KPIRow label="30-Day Retention" value={<span className={data.avg_retention_30d >= 0.4 ? "text-green-400" : "text-red-400"}>{fmtPct(data.avg_retention_30d)}</span>} />
        <KPIRow label="90-Day Retention" value={fmtPct(data.avg_retention_90d)} />
        <KPIRow label="Monthly Churn" value={<span className={data.churn_rate <= 0.05 ? "text-green-400" : "text-red-400"}>{fmtPct(data.churn_rate)}</span>} />
        <KPIRow label="Avg LTV" value={fmtCents(data.avg_ltv_cents)} />
        <KPIRow label="LTV:CAC Ratio" value={
          <span className={data.ltv_cac_ratio >= 3 ? "text-green-400" : data.ltv_cac_ratio >= 1 ? "text-yellow-400" : "text-red-400"}>
            {fmt(data.ltv_cac_ratio)}x
          </span>
        } />
        <KPIRow label="Retention Trend" value={trendIcon(data.retention_trend)} />
        <KPIRow label="Cohorts Analyzed" value={fmt(data.cohorts_analyzed)} />
      </div>

      {(data.best_cohort || data.worst_cohort) && (
        <div className="grid grid-cols-2 gap-3 pt-2">
          {data.best_cohort && (
            <div className="rounded border border-green-500/30 bg-green-500/10 p-3 text-xs">
              <p className="text-green-400 font-medium mb-1">Best Cohort</p>
              <p className="text-muted-foreground">{data.best_cohort.period}</p>
              <p className="tabular-nums">{fmtPct(data.best_cohort.retention_30d)} retention</p>
            </div>
          )}
          {data.worst_cohort && (
            <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-xs">
              <p className="text-red-400 font-medium mb-1">Worst Cohort</p>
              <p className="text-muted-foreground">{data.worst_cohort.period}</p>
              <p className="tabular-nums">{fmtPct(data.worst_cohort.retention_30d)} retention</p>
            </div>
          )}
        </div>
      )}

      {data.narrative && (
        <p className="text-xs text-muted-foreground italic border-t border-border/50 pt-3">{data.narrative}</p>
      )}
      <AlertList alerts={data.alerts} />
    </SectionCard>
  );
}

function CMOSummarySection({ summary }: { summary: CMOSummary }) {
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 className="h-5 w-5 text-primary" />
          <h3 className="font-semibold text-foreground">CMO Summary</h3>
        </div>
        <div className="flex gap-4 text-center">
          <div>
            <p className={`text-2xl font-bold tabular-nums ${scoreColor(summary.overall_marketing_score)}`}>
              {fmt(summary.overall_marketing_score)}/10
            </p>
            <p className="text-xs text-muted-foreground">Marketing Health</p>
          </div>
          <div>
            <p className="text-2xl font-bold tabular-nums text-accent">
              {fmt(summary.growth_efficiency_score)}/10
            </p>
            <p className="text-xs text-muted-foreground">Growth Efficiency</p>
          </div>
        </div>
      </div>

      {summary.narrative && (
        <p className="text-sm text-muted-foreground leading-relaxed border-l-2 border-primary/40 pl-3">
          {summary.narrative}
        </p>
      )}

      {summary.top_risks.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Top Risks</p>
          <div className="space-y-1.5">
            {summary.top_risks.map((r, i) => (
              <div key={i} className={`rounded px-3 py-2 text-xs flex gap-2 ${severityColor(r.severity)}`}>
                <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                <span><span className="font-semibold">{r.domain}:</span> {r.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.quick_wins.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">Quick Wins</p>
          <div className="space-y-1.5">
            {summary.quick_wins.map((w, i) => (
              <div key={i} className="rounded border border-border bg-card px-3 py-2 text-xs">
                <p className="text-foreground font-medium">{w.action}</p>
                <p className="text-muted-foreground mt-0.5">{w.estimated_impact} · Effort: {w.effort}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Input Form ────────────────────────────────────────────────────────────────

function CMOInputForm({
  onEnqueue,
  disabled,
}: {
  onEnqueue: (data: AgentJobRequest) => void;
  disabled?: boolean;
}) {
  const [form, setForm] = useState<CMOFormData>({});
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.campaign_csv && !form.funnel_csv && !form.cohort_csv) {
      setError("At least one data source is required.");
      return;
    }
    setError(null);
    onEnqueue({
      company_name:     form.company_name,
      reporting_period: form.period,
      campaign_csv:     form.campaign_csv,
      funnel_csv:       form.funnel_csv,
      cohort_csv:       form.cohort_csv,
    });
  }

  const SAMPLE_CAMPAIGN = `Campaign,Channel,Spend,Revenue,Conversions
Summer Sale,google,5000,18000,120
Brand Awareness,meta,3200,9600,85
Product Launch,email,800,4200,210`;

  const SAMPLE_FUNNEL = `id,stage,source,created,closed
1,Won,google,2024-01-05,2024-02-10
2,Lost,meta,2024-01-08,2024-02-15
3,Won,email,2024-01-12,2024-02-20`;

  const SAMPLE_COHORT = `cohort,users,retention_30d,retention_90d,ltv,cac
2024-01,200,45%,28%,1200,150
2024-02,180,42%,25%,1100,165
2024-03,220,48%,31%,1350,140`;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Company / Period */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Company Name</label>
          <input
            className="w-full rounded border border-border bg-muted px-3 py-2 text-sm text-foreground"
            placeholder="Acme Corp"
            value={form.company_name ?? ""}
            onChange={e => setForm(f => ({ ...f, company_name: e.target.value }))}
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Period</label>
          <input
            className="w-full rounded border border-border bg-muted px-3 py-2 text-sm text-foreground"
            placeholder="Q2 2025"
            value={form.period ?? ""}
            onChange={e => setForm(f => ({ ...f, period: e.target.value }))}
          />
        </div>
      </div>

      {/* CSV inputs — file drop or paste */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <AgentCsvInput
          label="Campaign CSV (Google Ads / Meta Ads)"
          value={form.campaign_csv ?? ""}
          onChange={(v) => setForm(f => ({ ...f, campaign_csv: v }))}
          sampleData={IS_DEMO ? SAMPLE_CAMPAIGN : undefined}
          description="Campaign, Channel, Spend, Revenue, Conversions"
          disabled={disabled}
        />
        <AgentCsvInput
          label="Funnel CSV (HubSpot / Salesforce)"
          value={form.funnel_csv ?? ""}
          onChange={(v) => setForm(f => ({ ...f, funnel_csv: v }))}
          sampleData={IS_DEMO ? SAMPLE_FUNNEL : undefined}
          description="id, stage, source, created, closed"
          disabled={disabled}
        />
        <AgentCsvInput
          label="Cohort CSV (Mixpanel / Amplitude)"
          value={form.cohort_csv ?? ""}
          onChange={(v) => setForm(f => ({ ...f, cohort_csv: v }))}
          sampleData={IS_DEMO ? SAMPLE_COHORT : undefined}
          description="cohort, users, retention_30d, retention_90d, ltv, cac"
          disabled={disabled}
        />
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={disabled}
        className="flex items-center gap-2 rounded bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {disabled && <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {disabled ? "Analyzing..." : "Run CMO Analysis"}
      </button>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CMODashboardPage() {
  const { orgId } = useCompanyContextStore();
  const [liveResult, setLiveResult] = useState<CMOResult | null>(null);
  const {
    enqueue, reset,
    status, progress, result, logs, error,
    isActive, isEnqueueing,
  } = useAgentJob("cmo");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const target = orgId ? `/context/${orgId}` : "/context/me";
        const res = await apiClient.get(target);
        const ctx = res.data?.data ?? res.data;
        const last = ctx?.last_cmo_result;
        if (!cancelled && last && typeof last === "object") {
          setLiveResult(last as CMOResult);
        }
      } catch {
        /* empty until analyze */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  const cmoResult = (result as CMOResult | null) ?? liveResult;

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-primary" />
          CMO Dashboard
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Marketing intelligence — campaign ROI, lead funnel, and cohort retention.
        </p>
      </div>

      {(isActive || status === "failed") && (
        <AgentJobPanel
          status={status}
          progress={progress}
          logs={logs}
          error={error}
          agentLabel="CMO"
          onReset={reset}
        />
      )}

      <div className="rounded-lg border border-border bg-card p-5">
        <h2 className="font-semibold text-foreground mb-4">Input Data</h2>
        <CMOInputForm onEnqueue={enqueue} disabled={isActive || isEnqueueing} />
      </div>

      {cmoResult && (
        <div className="space-y-6">
          {cmoResult.cmo_summary && <CMOSummarySection summary={cmoResult.cmo_summary} />}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {cmoResult.campaigns && <CampaignSection data={cmoResult.campaigns} />}
            {cmoResult.funnel && <FunnelSection data={cmoResult.funnel} />}
            {cmoResult.cohorts && <CohortSection data={cmoResult.cohorts} />}
          </div>

          {cmoResult.error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              Pipeline error: {cmoResult.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
