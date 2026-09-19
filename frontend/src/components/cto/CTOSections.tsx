"use client";

import { Server, TrendingDown, TrendingUp, Minus, GitBranch, AlertTriangle, Zap } from "lucide-react";
import { SectionCard, SeverityBadge } from "./SectionCard";
import { fmtCents, healthColor, type InfraData, type TechDebtData, type IncidentData, type VelocityData } from "./types";

// ── Trend icon ─────────────────────────────────────────────────────────────────

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up")   return <TrendingUp  className="h-4 w-4 text-emerald-400" aria-label="Trending up" />;
  if (trend === "down") return <TrendingDown className="h-4 w-4 text-destructive" aria-label="Trending down" />;
  return <Minus className="h-4 w-4 text-muted-foreground" aria-label="Stable" />;
}

// ── Infrastructure Cost ────────────────────────────────────────────────────────

export function InfraSection({ data }: { data: InfraData }) {
  return (
    <SectionCard title="Infrastructure Cost" icon={<Server className="h-4 w-4 text-primary" aria-hidden="true" />}>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Total Spend", value: fmtCents(data.total_cost_cents) },
          { label: "Est. Waste",  value: fmtCents(data.waste_estimate_cents), warning: data.waste_estimate_cents > 500000 },
          { label: "MoM Change",  value: data.mom_change_pct !== null ? `${data.mom_change_pct > 0 ? "+" : ""}${data.mom_change_pct.toFixed(1)}%` : "N/A" },
          { label: "Drivers",     value: `${data.top_cost_drivers.length} services` },
        ].map((m) => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.warning ? "text-orange-400" : "text-foreground"}`}>
              {m.value}
            </p>
          </div>
        ))}
      </div>

      <div className="mb-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">TOP COST DRIVERS</p>
        <div className="space-y-1.5">
          {data.top_cost_drivers.slice(0, 5).map((d) => (
            <div key={d.service} className="flex items-center gap-2">
              <div className="h-5 flex-1 overflow-hidden rounded-sm bg-muted/30">
                <div className="h-full rounded-sm bg-primary/30" style={{ width: `${d.pct}%` }} />
              </div>
              <span className="w-32 truncate text-right text-xs text-muted-foreground">{d.service}</span>
              <span className="w-20 text-right font-mono text-xs text-foreground">{fmtCents(d.cost_cents)}</span>
              <span className="w-10 text-right text-xs text-muted-foreground">{d.pct}%</span>
            </div>
          ))}
        </div>
      </div>

      {data.alerts.length > 0 && (
        <div className="space-y-1">
          {data.alerts.map((a, i) => (
            <p
              key={i}
              className={`rounded p-2 text-xs ${
                a.level === "critical" ? "bg-destructive/10 text-destructive" : "bg-orange-500/10 text-orange-400"
              }`}
            >
              {a.message}
            </p>
          ))}
        </div>
      )}

      <p className="mt-3 text-xs italic text-muted-foreground">{data.narrative}</p>
    </SectionCard>
  );
}

// ── Technical Debt ─────────────────────────────────────────────────────────────

export function TechDebtSection({ data }: { data: TechDebtData }) {
  const scoreColor = healthColor(data.debt_score);
  return (
    <SectionCard title="Technical Debt" icon={<GitBranch className="h-4 w-4 text-accent" aria-hidden="true" />}>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Debt Score",   value: `${data.debt_score.toFixed(1)}/10`, cls: scoreColor },
          { label: "Commits",      value: data.total_commits.toString() },
          { label: "Contributors", value: data.active_contributors.toString() },
          { label: "Churn Rate",   value: `${(data.churn_rate * 100).toFixed(1)}%` },
        ].map((m) => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.cls ?? "text-foreground"}`}>{m.value}</p>
          </div>
        ))}
      </div>

      {data.hotspot_files.length > 0 && (
        <div className="mb-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">HOTSPOT FILES</p>
          <div className="space-y-1">
            {data.hotspot_files.slice(0, 5).map((f) => (
              <div key={f.file} className="flex items-center justify-between text-xs">
                <span className="flex-1 truncate font-mono text-foreground">{f.file}</span>
                <span className="ml-3 text-muted-foreground">{f.changes} changes</span>
                {f.bus_factor_risk && (
                  <span className="ml-2 text-destructive" role="img" aria-label="Bus factor risk">⚠ bus factor</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs italic text-muted-foreground">{data.narrative}</p>
    </SectionCard>
  );
}

// ── Incident & Reliability ─────────────────────────────────────────────────────

export function IncidentSection({ data }: { data: IncidentData }) {
  return (
    <SectionCard title="Incident & Reliability" icon={<AlertTriangle className="h-4 w-4 text-yellow-400" aria-hidden="true" />}>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Total",        value: data.total_incidents.toString() },
          { label: "MTTR",         value: data.mttr_hours !== null ? `${data.mttr_hours.toFixed(1)}h` : "N/A", warning: (data.mttr_hours ?? 0) > 4 },
          { label: "SLA Breaches", value: `${data.sla_breach_count} (${data.sla_breach_pct.toFixed(0)}%)`, warning: data.sla_breach_pct > 20 },
          { label: "Trend",        value: data.trend.charAt(0).toUpperCase() + data.trend.slice(1) },
        ].map((m) => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums ${m.warning ? "text-orange-400" : "text-foreground"}`}>
              {m.value}
            </p>
          </div>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {Object.entries(data.by_severity).map(([sev, cnt]) => (
          <div key={sev} className="flex items-center gap-1.5">
            <SeverityBadge severity={sev} />
            <span className="text-xs text-muted-foreground">{cnt as number}</span>
          </div>
        ))}
      </div>

      <p className="text-xs italic text-muted-foreground">{data.narrative}</p>
    </SectionCard>
  );
}

// ── Engineering Velocity ───────────────────────────────────────────────────────

export function VelocitySection({ data }: { data: VelocityData }) {
  return (
    <SectionCard title="Engineering Velocity" icon={<Zap className="h-4 w-4 text-yellow-400" aria-hidden="true" />}>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Avg Velocity",   value: `${data.avg_velocity} pts` },
          { label: "Trend",          value: data.velocity_trend.charAt(0).toUpperCase() + data.velocity_trend.slice(1), icon: <TrendIcon trend={data.velocity_trend} /> },
          { label: "Predictability", value: `${(data.predictability_score * 100).toFixed(0)}%`, warning: data.predictability_score < 0.70 },
          { label: "Carryover",      value: `${(data.carryover_ratio * 100).toFixed(0)}%`,      warning: data.carryover_ratio > 0.20 },
        ].map((m) => (
          <div key={m.label} className="rounded-md bg-muted/40 p-3">
            <p className="text-[10px] uppercase text-muted-foreground">{m.label}</p>
            <div className="mt-1 flex items-center gap-1">
              {m.icon}
              <p className={`text-lg font-bold tabular-nums ${m.warning ? "text-orange-400" : "text-foreground"}`}>
                {m.value}
              </p>
            </div>
          </div>
        ))}
      </div>

      {data.sprint_series.length > 0 && (
        <div className="mb-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">SPRINT COMPLETION RATE</p>
          <div className="space-y-1.5">
            {data.sprint_series.slice(-6).map((s) => (
              <div key={s.sprint} className="flex items-center gap-2">
                <span className="w-24 truncate text-xs text-muted-foreground">{s.sprint}</span>
                <div className="h-4 flex-1 overflow-hidden rounded-sm bg-muted/30">
                  <div
                    className={`h-full rounded-sm ${
                      s.completion_rate_pct >= 80
                        ? "bg-emerald-500/50"
                        : s.completion_rate_pct >= 60
                        ? "bg-yellow-500/50"
                        : "bg-destructive/50"
                    }`}
                    style={{ width: `${Math.min(100, s.completion_rate_pct)}%` }}
                    role="progressbar"
                    aria-valuenow={Math.round(s.completion_rate_pct)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                  />
                </div>
                <span className="w-10 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {s.completion_rate_pct.toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs italic text-muted-foreground">{data.narrative}</p>
    </SectionCard>
  );
}
