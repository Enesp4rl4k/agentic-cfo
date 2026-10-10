"use client";

import { useEffect, useState } from "react";
import {
  Users, TrendingUp, TrendingDown, AlertTriangle,
  BarChart2, DollarSign, UserMinus, UserCheck,
  ChevronDown,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { AgentCsvInput } from "@/components/ui/agent-csv-input";
import { useCompanyContextStore } from "@/store/companyContext";
import { DomainPanel } from "@/components/domains/DomainPanel";
import { RoleDashboardHeader } from "@/components/ui/role-dashboard-header";
import { useI18n } from "@/hooks/useI18n";

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// ── Types ─────────────────────────────────────────────────────────────────────

interface HeadcountData {
  total_headcount: number;
  total_fte: number;
  new_hires_30d: number;
  departures_30d: number;
  net_headcount_change: number;
  by_department: Record<string, { headcount: number; fte: number; avg_tenure_years: number }>;
  by_level: Record<string, number>;
  avg_tenure_years: number;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface AttritionData {
  total_attritions: number;
  voluntary_attritions: number;
  involuntary_attritions: number;
  annualized_attrition_rate: number;
  avg_tenure_at_departure: number;
  cost_of_attrition: number;
  top_reasons: Array<{ reason: string; count: number; pct: number }>;
  high_risk_roles: Array<{ role: string; department: string; risk_score: number; reason: string }>;
  by_department: Record<string, { count: number; rate: number }>;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface CompensationData {
  total_payroll: number;
  avg_salary: number;
  median_salary: number;
  salary_range_min: number;
  salary_range_max: number;
  below_market_pct: number;
  above_market_pct: number;
  equity_burn_annual: number;
  benefits_cost_annual: number;
  by_level: Record<string, { avg_salary: number; count: number; market_alignment: string }>;
  alerts: Array<{ level: string; message: string }>;
  narrative: string;
}

interface CHROSummary {
  overall_hr_score: number;
  component_scores: Record<string, number>;
  top_risks: Array<{ domain: string; severity: string; message: string }>;
  quick_wins: Array<{ action: string; estimated_impact: string; effort: string }>;
  narrative: string;
}

interface CHROResult {
  job_id: string;
  headcount: HeadcountData | null;
  attrition: AttritionData | null;
  compensation: CompensationData | null;
  chro_summary: CHROSummary | null;
  error: string | null;
}

// ── Placeholder CSV data ──────────────────────────────────────────────────────

const PH = {
  headcount: `employee_id,name,department,level,role,location,fte,start_date,status
EMP001,Alice Chen,Engineering,L4,Senior Engineer,Istanbul,1.0,2021-03-15,active
EMP002,Bob Kim,Engineering,L3,Engineer,Istanbul,1.0,2022-07-01,active
EMP003,Carol Davis,Product,L5,Principal PM,Remote,1.0,2020-01-10,active
EMP004,Dan Ortiz,Sales,L2,Account Executive,Ankara,1.0,2023-02-28,active
EMP005,Eva Müller,HR,L3,HR Business Partner,Istanbul,1.0,2021-09-20,active`,

  attrition: `employee_id,department,level,role,tenure_years,departure_date,departure_type,reason,replaced
EMP010,Engineering,L3,Engineer,1.5,2024-01-15,voluntary,better_offer,no
EMP011,Sales,L2,Account Executive,0.8,2024-02-01,voluntary,compensation,yes
EMP012,Product,L4,Senior PM,3.2,2024-02-20,voluntary,career_growth,no
EMP013,Engineering,L5,Staff Engineer,4.1,2024-03-10,voluntary,better_offer,no
EMP014,Marketing,L2,Marketing Analyst,1.1,2024-03-25,involuntary,performance,yes`,

  compensation: `employee_id,department,level,role,base_salary,equity_annual,benefits_annual,market_rate,location
EMP001,Engineering,L4,Senior Engineer,95000,15000,12000,105000,Istanbul
EMP002,Engineering,L3,Engineer,72000,8000,10000,78000,Istanbul
EMP003,Product,L5,Principal PM,115000,20000,14000,120000,Remote
EMP004,Sales,L2,Account Executive,55000,0,8000,58000,Ankara
EMP005,HR,L3,HR Business Partner,68000,5000,10000,70000,Istanbul`,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (isNaN(v)) return "—";
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(decimals)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(decimals)}K`;
  return v.toFixed(decimals);
}

function pct(n: unknown): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : (v * 100).toFixed(1) + "%";
}

function severityClass(level: string): string {
  switch (level.toLowerCase()) {
    case "critical": return "text-red-400 bg-red-400/10 border-red-400/30";
    case "high":     return "text-orange-400 bg-orange-400/10 border-orange-400/30";
    case "medium":   return "text-yellow-400 bg-yellow-400/10 border-yellow-400/30";
    default:         return "text-blue-400 bg-blue-400/10 border-blue-400/30";
  }
}

function effortClass(effort: string): string {
  switch (effort) {
    case "low":    return "bg-emerald-500/20 text-emerald-400";
    case "medium": return "bg-yellow-500/20 text-yellow-400";
    case "high":   return "bg-red-500/20 text-red-400";
    default:       return "bg-zinc-500/20 text-zinc-400";
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionCard({ title, icon, children }: {
  title: string; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function AlertList({ alerts }: { alerts: Array<{ level: string; message: string }> }) {
  const { t } = useI18n();
  if (!alerts?.length) return <p className="text-xs text-muted-foreground">{t.roleDashboards.chro.body.noAlerts}</p>;
  return (
    <ul className="space-y-1.5">
      {alerts.map((a, i) => (
        <li key={i} className={`rounded border px-3 py-2 text-xs ${severityClass(a.level)}`}>
          <span className="mr-1.5 font-semibold uppercase">{a.level}</span>
          {a.message}
        </li>
      ))}
    </ul>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-muted/40 p-2 text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}

// ── Section components ────────────────────────────────────────────────────────

function HeadcountSection({ data }: { data: HeadcountData }) {
  const { t } = useI18n();
  return (
    <SectionCard title={t.roleDashboards.chro.sections.headcountOverview} icon={<Users className="h-4 w-4 text-pink-400" />}>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatBlock label={t.roleDashboards.chro.body.totalHeadcount} value={String(data.total_headcount)} />
        <StatBlock label={t.roleDashboards.chro.body.totalFte} value={fmt(data.total_fte, 1)} />
        <StatBlock label={t.roleDashboards.chro.body.newHires30d} value={String(data.new_hires_30d)} />
        <StatBlock label={t.roleDashboards.chro.body.avgTenure} value={fmt(data.avg_tenure_years) + " " + t.roleDashboards.chro.body.yrs} />
      </div>

      <div className="mb-3 flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">{t.roleDashboards.chro.body.netChange30d}</span>
        <span className={data.net_headcount_change >= 0 ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold"}>
          {data.net_headcount_change >= 0 ? "+" : ""}{data.net_headcount_change}
        </span>
      </div>

      {Object.keys(data.by_department ?? {}).length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t.roleDashboards.chro.body.byDepartment}</p>
          <div className="space-y-1">
            {Object.entries(data.by_department).slice(0, 5).map(([dept, d]) => (
              <div key={dept} className="flex items-center justify-between rounded bg-muted/30 px-2 py-1 text-xs">
                <span className="font-medium">{dept}</span>
                <span className="text-muted-foreground">{d.headcount} FTE · {fmt(d.avg_tenure_years)} {t.roleDashboards.chro.body.yrs} {t.roleDashboards.chro.body.avg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <AlertList alerts={data.alerts} />
      {data.narrative && <p className="mt-2 text-xs text-muted-foreground">{data.narrative}</p>}
    </SectionCard>
  );
}

function AttritionSection({ data }: { data: AttritionData }) {
  const { t } = useI18n();
  return (
    <SectionCard title={t.roleDashboards.chro.sections.attritionAnalysis} icon={<UserMinus className="h-4 w-4 text-red-400" />}>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatBlock label={t.roleDashboards.chro.body.totalAttritions} value={String(data.total_attritions)} />
        <StatBlock label={t.roleDashboards.chro.body.voluntary} value={String(data.voluntary_attritions)} />
        <StatBlock label={t.roleDashboards.chro.body.annualRate} value={pct(data.annualized_attrition_rate)} />
        <StatBlock label={t.roleDashboards.chro.body.attritionCost} value={"₺" + fmt(data.cost_of_attrition)} />
      </div>

      {data.top_reasons?.length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t.roleDashboards.chro.body.topDepartureReasons}</p>
          {data.top_reasons.slice(0, 4).map((r, i) => (
            <div key={i} className="mb-1 flex items-center gap-2 text-xs">
              <div className="h-1.5 rounded-full bg-red-400/40" style={{ width: `${Math.max(8, r.pct)}%` }} aria-hidden="true" />
              <span className="capitalize">{r.reason.replace(/_/g, " ")}</span>
              <span className="ml-auto text-muted-foreground">{r.count}× ({r.pct.toFixed(0)}%)</span>
            </div>
          ))}
        </div>
      )}

      {data.high_risk_roles?.length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-red-400">{t.roleDashboards.chro.body.highAttritionRiskRoles}</p>
          <ul className="space-y-1">
            {data.high_risk_roles.slice(0, 4).map((r, i) => (
              <li key={i} className="rounded border border-red-400/20 bg-red-400/5 px-2 py-1 text-xs">
                <span className="font-medium">{r.role}</span>
                <span className="ml-1 text-muted-foreground">({r.department})</span>
                <span className="ml-2 text-red-400">{t.roleDashboards.chro.body.riskLabel} {fmt(r.risk_score, 0)}/10</span>
                {r.reason && <span className="ml-2 text-muted-foreground">— {r.reason}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <AlertList alerts={data.alerts} />
      {data.narrative && <p className="mt-2 text-xs text-muted-foreground">{data.narrative}</p>}
    </SectionCard>
  );
}

function CompensationSection({ data }: { data: CompensationData }) {
  const { t } = useI18n();
  return (
    <SectionCard title={t.roleDashboards.chro.sections.compensationAnalysis} icon={<DollarSign className="h-4 w-4 text-emerald-400" />}>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatBlock label={t.roleDashboards.chro.body.totalPayroll} value={"₺" + fmt(data.total_payroll)} />
        <StatBlock label={t.roleDashboards.chro.body.avgSalary} value={"₺" + fmt(data.avg_salary)} />
        <StatBlock label={t.roleDashboards.chro.body.equityBurn} value={"₺" + fmt(data.equity_burn_annual)} />
        <StatBlock label={t.roleDashboards.chro.body.benefitsCost} value={"₺" + fmt(data.benefits_cost_annual)} />
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="rounded bg-muted/30 p-2 text-xs">
          <span className="text-muted-foreground">{t.roleDashboards.chro.body.belowMarket} </span>
          <span className={data.below_market_pct > 0.2 ? "text-red-400 font-semibold" : "text-emerald-400 font-semibold"}>
            {pct(data.below_market_pct)}
          </span>
        </div>
        <div className="rounded bg-muted/30 p-2 text-xs">
          <span className="text-muted-foreground">{t.roleDashboards.chro.body.aboveMarket} </span>
          <span className="font-semibold">{pct(data.above_market_pct)}</span>
        </div>
      </div>

      {Object.keys(data.by_level ?? {}).length > 0 && (
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">{t.roleDashboards.chro.body.byLevel}</p>
          <div className="space-y-1">
            {Object.entries(data.by_level).slice(0, 5).map(([level, d]) => (
              <div key={level} className="flex items-center justify-between rounded bg-muted/30 px-2 py-1 text-xs">
                <span className="font-medium">{level}</span>
                <span className="text-muted-foreground">₺{fmt(d.avg_salary)} {t.roleDashboards.chro.body.avg} · {d.count} {t.roleDashboards.chro.body.employees}</span>
                <span className={d.market_alignment === "below" ? "text-red-400" : d.market_alignment === "above" ? "text-emerald-400" : "text-muted-foreground"}>
                  {d.market_alignment}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <AlertList alerts={data.alerts} />
      {data.narrative && <p className="mt-2 text-xs text-muted-foreground">{data.narrative}</p>}
    </SectionCard>
  );
}

function CHROSummarySection({ data }: { data: CHROSummary }) {
  const { t } = useI18n();
  const scoreColor = (s: number) => s >= 7 ? "text-emerald-400" : s >= 5 ? "text-yellow-400" : "text-red-400";

  return (
    <SectionCard title={t.roleDashboards.chro.sections.hrHealthSummary} icon={<BarChart2 className="h-4 w-4 text-sage-400" />}>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded bg-muted/40 p-2 text-center">
          <p className="text-xs text-muted-foreground">{t.roleDashboards.chro.body.hrScore}</p>
          <p className={`text-lg font-bold tabular-nums ${scoreColor(data.overall_hr_score)}`}>
            {fmt(data.overall_hr_score)}/10
          </p>
        </div>
        {Object.entries(data.component_scores ?? {}).slice(0, 3).map(([k, v]) => (
          <div key={k} className="rounded bg-muted/40 p-2 text-center">
            <p className="text-xs text-muted-foreground capitalize">{k.replace(/_/g, " ")}</p>
            <p className={`text-lg font-bold tabular-nums ${scoreColor(v as number)}`}>
              {fmt(v as number)}/10
            </p>
          </div>
        ))}
      </div>

      {data.top_risks?.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-semibold">{t.roleDashboards.chro.body.topHrRisks}</p>
          <ul className="space-y-1">
            {data.top_risks.slice(0, 5).map((r, i) => (
              <li key={i} className={`rounded border px-3 py-1.5 text-xs ${severityClass(r.severity)}`}>
                <span className="mr-1.5 font-semibold uppercase">{r.severity}</span>
                <span className="mr-1 text-muted-foreground">[{r.domain}]</span>
                {r.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.quick_wins?.length > 0 && (
        <div className="mb-3">
          <p className="mb-2 text-xs font-semibold">{t.roleDashboards.chro.body.quickWins}</p>
          <ul className="space-y-2">
            {data.quick_wins.map((w, i) => (
              <li key={i} className="rounded border border-border bg-muted/20 p-2 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium">{w.action}</span>
                  <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${effortClass(w.effort)}`}>
                    {w.effort} {t.roleDashboards.chro.body.effort}
                  </span>
                </div>
                <p className="mt-1 text-muted-foreground">{w.estimated_impact}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.narrative && (
        <div className="rounded border border-border bg-muted/10 p-3 text-xs text-muted-foreground">
          {data.narrative}
        </div>
      )}
    </SectionCard>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CHRODashboardPage() {
  const { t } = useI18n();
  const { orgId, activeCFOJobId } = useCompanyContextStore();
  const [headcountCsv,  setHeadcountCsv]  = useState("");
  const [attritionCsv,  setAttritionCsv]  = useState("");
  const [compensationCsv, setCompensationCsv] = useState("");
  const [company,  setCompany]  = useState("");
  const [period,   setPeriod]   = useState("");
  const [loading,  setLoading]  = useState(false);
  const [result,   setResult]   = useState<CHROResult | null>(null);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const target = orgId ? `/context/${orgId}` : "/context/me";
        const res = await apiClient.get(target);
        const ctx = res.data?.data ?? res.data;
        if (cancelled || !ctx) return;
        if (ctx.company_name) setCompany(String(ctx.company_name));
        if (ctx.reporting_period) setPeriod(String(ctx.reporting_period));
        const last = ctx.last_chro_result;
        if (last && typeof last === "object") setResult(last as CHROResult);
      } catch {
        /* empty until analyze */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!headcountCsv || !attritionCsv || !compensationCsv) {
      setError(t.roleDashboards.chro.body.validationError);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<{ job_id: string; headcount: HeadcountData | null; attrition: AttritionData | null; compensation: CompensationData | null; chro_summary: CHROSummary | null; error: string | null }>(
        "/chro/analyze",
        {
          company_name:     company       || null,
          analysis_period:  period        || null,
          headcount_csv:    headcountCsv,
          attrition_csv:    attritionCsv,
          compensation_csv: compensationCsv,
        }
      );
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t.roleDashboards.chro.body.unknownError);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
      {/* Header */}
      <RoleDashboardHeader
        title={t.roleDashboards.chro.title}
        description={t.roleDashboards.chro.description}
      />

      {/* The one entry point: real data, or what is missing and how to get it.
          The CSV boxes below are the fallback for someone who already has the
          text in hand; nothing here estimates HR figures from finance. */}
      <DomainPanel
        alan="chro"
        jobId={activeCFOJobId}
        onResult={(r) => setResult(r as unknown as CHROResult)}
      />

      {/* CSV yapıştırarak çalıştır */}
      <details open={!result} className="group rounded-xl border border-border/80 bg-card">
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold">{t.roleDashboards.chro.body.csvManualHeading}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <form onSubmit={handleSubmit} className="space-y-4 border-t border-border/80 p-4 sm:p-5">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
              <label htmlFor="chro-company" className="mb-1 block text-xs font-medium">{t.roleDashboards.chro.body.companyName}</label>
            <input
              id="chro-company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
              <label htmlFor="chro-period" className="mb-1 block text-xs font-medium">{t.roleDashboards.chro.body.period}</label>
            <input
              id="chro-period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q2"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <AgentCsvInput
            label={t.roleDashboards.chro.body.headcountCsvLabel}
            value={headcountCsv}
            onChange={setHeadcountCsv}
            sampleData={IS_DEMO ? PH.headcount : undefined}
            description="employee_id, department, level, role, fte, start_date, status"
            disabled={loading}
          />
          <AgentCsvInput
            label={t.roleDashboards.chro.body.attritionCsvLabel}
            value={attritionCsv}
            onChange={setAttritionCsv}
            sampleData={IS_DEMO ? PH.attrition : undefined}
            description="employee_id, department, tenure_years, departure_type, reason"
            disabled={loading}
          />
          <AgentCsvInput
            label={t.roleDashboards.chro.body.compensationCsvLabel}
            value={compensationCsv}
            onChange={setCompensationCsv}
            sampleData={IS_DEMO ? PH.compensation : undefined}
            description="employee_id, level, base_salary, equity_annual, market_rate"
            disabled={loading}
          />
        </div>

        {error && (
          <p role="alert" className="mb-3 rounded border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {loading ? t.roleDashboards.chro.body.analyzing : t.roleDashboards.chro.body.runAnalysis}
          </button>
          <button
            type="button"
            onClick={() => { /* sample data loaded via AgentCsvInput */ }}
            className="hidden rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            {t.roleDashboards.chro.body.loadExampleData}
          </button>
        </div>
      </form>
      </details>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {result.chro_summary && <CHROSummarySection data={result.chro_summary} />}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {result.attrition && <div className={result.headcount ? "lg:col-span-2" : ""}><AttritionSection data={result.attrition} /></div>}
            {result.headcount && <HeadcountSection data={result.headcount} />}
            {result.compensation && <CompensationSection data={result.compensation} />}
          </div>

          {result.error && (
            <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
              {t.roleDashboards.chro.body.pipelineError} {result.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
