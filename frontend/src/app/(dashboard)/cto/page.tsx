"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Server,
  GitBranch,
  AlertTriangle,
  Zap,
  TrendingDown,
  TrendingUp,
  Minus,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CTOResult {
  job_id: string;
  infra: InfraData | null;
  tech_debt: TechDebtData | null;
  incidents: IncidentData | null;
  velocity: VelocityData | null;
  cto_summary: CTOSummary | null;
  awaiting_review: boolean;
  min_confidence: number | null;
  error: string | null;
}

interface InfraData {
  total_cost_cents: number;
  waste_estimate_cents: number;
  mom_change_pct: number | null;
  top_cost_drivers: { service: string; cost_cents: number; pct: number }[];
  by_environment: Record<string, number>;
  alerts: { level: string; message: string }[];
  narrative: string;
}

interface TechDebtData {
  total_commits: number;
  active_contributors: number;
  churn_rate: number;
  debt_score: number;
  hotspot_files: { file: string; changes: number; authors: number; bus_factor_risk: boolean }[];
  refactor_priorities: { area: string; severity: string; changes_in_period: number; estimated_days: number }[];
  narrative: string;
}

interface IncidentData {
  total_incidents: number;
  by_severity: Record<string, number>;
  mttr_hours: number | null;
  mttd_hours: number | null;
  sla_breach_count: number;
  sla_breach_pct: number;
  recurring_services: { service: string; count: number; pct: number }[];
  trend: string;
  alerts: { level: string; message: string }[];
  narrative: string;
}

interface VelocityData {
  sprints_analyzed: number;
  avg_velocity: number;
  velocity_trend: string;
  predictability_score: number;
  carryover_ratio: number;
  bottlenecks: { area: string; impact: string }[];
  sprint_series: { sprint: string; planned: number; completed: number; completion_rate_pct: number }[];
  narrative: string;
}

interface CTOSummary {
  overall_health_score: number;
  component_scores: Record<string, number>;
  top_risks: { domain: string; severity: string; message: string }[];
  quick_wins: { action: string; estimated_impact: string; effort: string }[];
  narrative: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function healthColor(score: number): string {
  if (score <= 3) return "text-emerald-400";
  if (score <= 6) return "text-yellow-400";
  if (score <= 8) return "text-orange-400";
  return "text-destructive";
}

function healthLabel(score: number): string {
  if (score <= 3) return "Healthy";
  if (score <= 6) return "Moderate";
  if (score <= 8) return "At Risk";
  return "Critical";
}

function trendIcon(trend: string) {
  if (trend === "up")   return <TrendingUp  className="h-4 w-4 text-emerald-400" />;
  if (trend === "down") return <TrendingDown className="h-4 w-4 text-destructive" />;
  return <Minus className="h-4 w-4 text-muted-foreground" />;
}

function severityBadge(severity: string) {
  const cls: Record<string, string> = {
    critical: "bg-destructive/20 text-destructive border-destructive/30",
    high:     "bg-orange-500/20 text-orange-400 border-orange-500/30",
    medium:   "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    low:      "bg-muted text-muted-foreground border-border",
  };
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${cls[severity] ?? cls.low}`}>
      {severity}
    </span>
  );
}

// ── Input form ────────────────────────────────────────────────────────────────

function CTOInputForm({ onResult }: { onResult: (r: CTOResult) => void }) {
  const [billingCsv, setBillingCsv]   = useState("");
  const [gitLog, setGitLog]           = useState("");
  const [incidentCsv, setIncidentCsv] = useState("");
  const [sprintCsv, setSprintCsv]     = useState("");
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${apiBase}/api/v1/cto/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cloud_billing_csv: billingCsv || null,
          git_log_text:      gitLog || null,
          incident_csv:      incidentCsv || null,
          sprint_csv:        sprintCsv || null,
        }),
      });
      const json = await res.json();
      if (!res.ok || json.error) throw new Error(json.error ?? json.detail ?? "Analysis failed");
      onResult(json.data as CTOResult);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Paste at least one data source. All fields are optional — agents skip missing inputs.
      </p>
      {[
        { label: "Cloud Billing CSV", value: billingCsv, set: setBillingCsv, placeholder: "service,cost,date\nEC2,1234.56,2024-06" },
        { label: "Git Log (git log --stat)", value: gitLog, set: setGitLog, placeholder: "commit abc1234\nAuthor: dev@company.com\n..." },
        { label: "Incident CSV", value: incidentCsv, set: setIncidentCsv, placeholder: "id,severity,service,started_at,resolved_at\n1,critical,api,2024-06-01T10:00:00Z,2024-06-01T14:00:00Z" },
        { label: "Sprint CSV", value: sprintCsv, set: setSprintCsv, placeholder: "sprint_name,planned_points,completed_points\nSprint 1,40,36" },
      ].map(({ label, value, set, placeholder }) => (
        <div key={label}>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">{label}</label>
          <textarea
            className="w-full rounded-md border border-border bg-card px-3 py-2 font-mono text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary"
            rows={4}
            placeholder={placeholder}
            value={value}
            onChange={e => set(e.target.value)}
          />
        </div>
      ))}

      {error && <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}

      <button
        type="submit"
        disabled={loading}
        className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {loading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
        {loading ? "Analyzing…" : "Run CTO Analysis"}
      </button>
    </form>
  );
}

// ── Result sections ────────────────────────────────────────────────────────────

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        className="flex w-full items-center justify-between p-4 text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          {icon}
          {title}
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>
      {open && <div className="border-t border-border p-4">{children}</div>}
    </div>
  );
}

function InfraSection({ data }: { data: InfraData }) {
  return (
    <SectionCard title="Infrastructure Cost" icon={<Server className="h-4 w-4 text-primary" />}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
        {[
          { label: "Total Spend", value: fmt(data.total_cost_cents) },
          { label: "Est. Waste",  value: fmt(data.waste_estimate_cents), warning: data.waste_estimate_cents > 500000 },
          { label: "MoM Change",  value: data.mom_change_pct !== null ? `${data.mom_change_pct > 0 ? "+" : ""}${data.mom_change_pct.toFixed(1)}%` : "N/A" },
          { label: "Drivers",     value: `${data.top_cost_drivers.length} services` },
        ].map(m => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.warning ? "text-warning" : "text-foreground"}`}>{m.value}</p>
          </div>
        ))}
      </div>

      <div className="mb-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">TOP COST DRIVERS</p>
        <div className="space-y-1.5">
          {data.top_cost_drivers.slice(0, 5).map(d => (
            <div key={d.service} className="flex items-center gap-2">
              <div className="flex-1 rounded-sm bg-muted/30 h-5 overflow-hidden">
                <div className="h-full bg-primary/30 rounded-sm" style={{ width: `${d.pct}%` }} />
              </div>
              <span className="w-32 truncate text-right text-xs text-muted-foreground">{d.service}</span>
              <span className="w-20 text-right text-xs font-mono text-foreground">{fmt(d.cost_cents)}</span>
              <span className="w-10 text-right text-xs text-muted-foreground">{d.pct}%</span>
            </div>
          ))}
        </div>
      </div>

      {data.alerts.length > 0 && (
        <div className="space-y-1">
          {data.alerts.map((a, i) => (
            <p key={i} className={`text-xs rounded p-2 ${a.level === "critical" ? "bg-destructive/10 text-destructive" : "bg-warning/10 text-warning"}`}>
              {a.message}
            </p>
          ))}
        </div>
      )}

      <p className="mt-3 text-xs text-muted-foreground italic">{data.narrative}</p>
    </SectionCard>
  );
}

function TechDebtSection({ data }: { data: TechDebtData }) {
  const scoreColor = healthColor(data.debt_score);
  return (
    <SectionCard title="Technical Debt" icon={<GitBranch className="h-4 w-4 text-accent" />}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
        {[
          { label: "Debt Score",    value: `${data.debt_score.toFixed(1)}/10`, className: scoreColor },
          { label: "Commits",       value: data.total_commits.toString() },
          { label: "Contributors",  value: data.active_contributors.toString() },
          { label: "Churn Rate",    value: `${(data.churn_rate * 100).toFixed(1)}%` },
        ].map(m => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.className ?? "text-foreground"}`}>{m.value}</p>
          </div>
        ))}
      </div>

      {data.hotspot_files.length > 0 && (
        <div className="mb-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">HOTSPOT FILES</p>
          <div className="space-y-1">
            {data.hotspot_files.slice(0, 5).map(f => (
              <div key={f.file} className="flex items-center justify-between text-xs">
                <span className="flex-1 truncate font-mono text-foreground">{f.file}</span>
                <span className="ml-3 text-muted-foreground">{f.changes} changes</span>
                {f.bus_factor_risk && <span className="ml-2 text-destructive">⚠ bus factor</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground italic">{data.narrative}</p>
    </SectionCard>
  );
}

function IncidentSection({ data }: { data: IncidentData }) {
  return (
    <SectionCard title="Incident & Reliability" icon={<AlertTriangle className="h-4 w-4 text-warning" />}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
        {[
          { label: "Total",       value: data.total_incidents.toString() },
          { label: "MTTR",        value: data.mttr_hours !== null ? `${data.mttr_hours.toFixed(1)}h` : "N/A", warning: (data.mttr_hours ?? 0) > 4 },
          { label: "SLA Breaches",value: `${data.sla_breach_count} (${data.sla_breach_pct.toFixed(0)}%)`, warning: data.sla_breach_pct > 20 },
          { label: "Trend",       value: data.trend.charAt(0).toUpperCase() + data.trend.slice(1) },
        ].map(m => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.warning ? "text-warning" : "text-foreground"}`}>{m.value}</p>
          </div>
        ))}
      </div>

      <div className="mb-3 flex gap-2 flex-wrap">
        {Object.entries(data.by_severity).map(([sev, cnt]) => (
          <div key={sev} className="flex items-center gap-1.5">
            {severityBadge(sev)}
            <span className="text-xs text-muted-foreground">{cnt}</span>
          </div>
        ))}
      </div>

      <p className="text-xs text-muted-foreground italic">{data.narrative}</p>
    </SectionCard>
  );
}

function VelocitySection({ data }: { data: VelocityData }) {
  return (
    <SectionCard title="Engineering Velocity" icon={<Zap className="h-4 w-4 text-yellow-400" />}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
        {[
          { label: "Avg Velocity",     value: `${data.avg_velocity} pts` },
          { label: "Trend",            value: data.velocity_trend.charAt(0).toUpperCase() + data.velocity_trend.slice(1), icon: trendIcon(data.velocity_trend) },
          { label: "Predictability",   value: `${(data.predictability_score * 100).toFixed(0)}%`, warning: data.predictability_score < 0.70 },
          { label: "Carryover",        value: `${(data.carryover_ratio * 100).toFixed(0)}%`, warning: data.carryover_ratio > 0.20 },
        ].map(m => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <div className="mt-1 flex items-center gap-1">
              {m.icon}
              <p className={`text-lg font-bold tabular-nums ${(m as { warning?: boolean }).warning ? "text-warning" : "text-foreground"}`}>{m.value}</p>
            </div>
          </div>
        ))}
      </div>

      {data.sprint_series.length > 0 && (
        <div className="mb-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">SPRINT COMPLETION RATE</p>
          <div className="space-y-1.5">
            {data.sprint_series.slice(-6).map(s => (
              <div key={s.sprint} className="flex items-center gap-2">
                <span className="w-24 truncate text-xs text-muted-foreground">{s.sprint}</span>
                <div className="flex-1 rounded-sm bg-muted/30 h-4 overflow-hidden">
                  <div
                    className={`h-full rounded-sm ${s.completion_rate_pct >= 80 ? "bg-emerald-500/50" : s.completion_rate_pct >= 60 ? "bg-yellow-500/50" : "bg-destructive/50"}`}
                    style={{ width: `${Math.min(100, s.completion_rate_pct)}%` }}
                  />
                </div>
                <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">{s.completion_rate_pct.toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground italic">{data.narrative}</p>
    </SectionCard>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTODashboardPage() {
  const [result, setResult] = useState<CTOResult | null>(null);

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight">CTO Dashboard</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Infrastructure costs · Technical debt · Incident analysis · Engineering velocity
        </p>
      </div>

      {/* Summary scorecard */}
      {result?.cto_summary && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Technology Health Score</h3>
            <span className={`text-2xl font-bold tabular-nums ${healthColor(result.cto_summary.overall_health_score)}`}>
              {result.cto_summary.overall_health_score.toFixed(1)}/10
              <span className="ml-2 text-sm font-normal">{healthLabel(result.cto_summary.overall_health_score)}</span>
            </span>
          </div>

          {/* Component scores */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 mb-4">
            {Object.entries(result.cto_summary.component_scores).map(([domain, score]) => (
              <div key={domain} className="text-center">
                <p className="text-[10px] uppercase text-muted-foreground">{domain.replace("_", " ")}</p>
                <p className={`text-base font-bold ${healthColor(score)}`}>{score.toFixed(1)}</p>
              </div>
            ))}
          </div>

          {/* Quick wins */}
          {result.cto_summary.quick_wins.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">QUICK WINS</p>
              <div className="space-y-1.5">
                {result.cto_summary.quick_wins.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full bg-emerald-500/20 text-center text-[10px] font-bold text-emerald-400">{i + 1}</span>
                    <div>
                      <span className="text-foreground">{w.action}</span>
                      <span className="ml-2 text-emerald-400">{w.estimated_impact}</span>
                      <span className="ml-2 text-muted-foreground">· {w.effort} effort</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="mt-3 text-xs text-muted-foreground italic">{result.cto_summary.narrative}</p>
        </div>
      )}

      {/* Agent sections */}
      {result ? (
        <div className="space-y-4">
          {result.infra     && <InfraSection     data={result.infra}     />}
          {result.tech_debt && <TechDebtSection  data={result.tech_debt} />}
          {result.incidents && <IncidentSection  data={result.incidents} />}
          {result.velocity  && <VelocitySection  data={result.velocity}  />}
          {!result.infra && !result.tech_debt && !result.incidents && !result.velocity && (
            <p className="text-sm text-muted-foreground">No agent data returned. Check input format.</p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-semibold">Run CTO Analysis</h3>
          <CTOInputForm onResult={setResult} />
        </div>
      )}

      {result && (
        <button
          onClick={() => setResult(null)}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          ← Run new analysis
        </button>
      )}
    </div>
  );
}
