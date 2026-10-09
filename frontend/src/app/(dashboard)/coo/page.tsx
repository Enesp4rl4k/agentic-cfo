"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo, useEffect } from "react";
import {
  Zap, TrendingDown, Clock, AlertCircle, CheckCircle, Users,
  ArrowUp, ArrowDown, Minus, ChevronDown,
} from "lucide-react";
import { AgentCsvInput } from "@/components/ui/agent-csv-input";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, BarChart, Bar, Cell,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import { formatPercent, formatNumber, getSeverityColorClass } from "@/lib/dashboard-utils";
import { useAgentJob } from "@/hooks/useAgentJob";
import { AgentJobPanel } from "@/components/ui/agent-job-panel";
import { DomainPanel } from "@/components/domains/DomainPanel";
import { useCompanyContextStore } from "@/store/companyContext";
import { RoleDashboardHeader } from "@/components/ui/role-dashboard-header";
import { useI18n } from "@/hooks/useI18n";

const IS_DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ProcessBottleneck {
  process_name: string;
  cycle_time: number; // days
  throughput: number; // items/day
  wip: number; // work in progress count
  constraint_type: "resource" | "policy" | "market" | "material";
  toc_recommendation: string;
  impact_score: number; // 0-100
}

interface SLATicket {
  ticket_id: string;
  title: string;
  assigned_to: string;
  created_date: string;
  due_date: string;
  hours_remaining: number;
  /** A 0–1 ordering score from the backend's rule, never a probability. */
  risk_score?: number;
  risk_level?: "kritik" | "yüksek" | "orta" | "düşük";
  priority: "critical" | "high" | "medium" | "low";
  status: string;
}

interface COOResult {
  job_id: string;
  processes: ProcessBottleneck[] | null;
  sla: { tickets: SLATicket[]; breach_rate: number; trend: Array<{ date: string; breach_pct: number }> } | null;
  error: string | null;
}

// ── Sample Data ────────────────────────────────────────────────────────────────

const SAMPLE_PROCESSES = `process_name,cycle_time,throughput,wip,constraint_type,impact_score
Order Processing,5,20,45,resource,92
Payment Verification,3,30,25,policy,78
Inventory Check,2,40,15,material,65
Shipping Preparation,4,25,35,resource,88
Quality Inspection,3,15,20,resource,72`;

const SAMPLE_SLA = `ticket_id,title,assigned_to,created_date,due_date,priority,status
T001,Sistem Entegrasyonu,Ali,2024-06-20,2024-07-25,critical,in_progress
T002,Veri Aktarımı,Fatma,2024-06-18,2024-07-20,high,in_progress
T003,API Geliştirme,Mehmet,2024-06-22,2024-07-30,high,in_progress
T004,Raporlama,Ayşe,2024-06-15,2024-07-18,medium,in_progress
T005,Kullanıcı Arayüzü,Can,2024-06-25,2024-08-05,medium,in_progress`;

// ── Helper functions ──────────────────────────────────────────────────────────

function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : v.toFixed(decimals);
}

function getConstraintColor(type: string): string {
  switch (type) {
    case "resource":
      return "#ef4444"; // red
    case "policy":
      return "#f97316"; // orange
    case "market":
      return "#3b82f6"; // blue
    case "material":
      return "#f59e0b"; // amber
    default:
      return "#6b7280"; // gray
  }
}

function getConstraintLabel(type: string, labels: Record<string, string>): string {
  return labels[type] || type;
}

// ── 3D-like Bubble Chart for Bottlenecks ──────────────────────────────────────

interface BubbleChartProps {
  processes: ProcessBottleneck[];
}

function BottleneckBubbleChart({ processes }: BubbleChartProps) {
  const { t } = useI18n();
  const data = processes.map((p) => ({
    name: p.process_name.slice(0, 12),
    cycle_time: p.cycle_time,
    throughput: p.throughput,
    wip: p.wip * 2, // scale for visibility
    constraint_type: p.constraint_type,
    impact_score: p.impact_score,
  }));

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <Zap className="h-4 w-4" />
        {t.roleDashboards.coo.sections.bottlenecks}
      </h3>
      <ResponsiveContainer width="100%" height={350}>
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis
            dataKey="cycle_time"
            name={t.roleDashboards.coo.body.cycleTimeAxis}
            stroke="currentColor"
            opacity={0.5}
          />
          <YAxis
            dataKey="throughput"
            name={t.roleDashboards.coo.body.throughputAxis}
            stroke="currentColor"
            opacity={0.5}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{ backgroundColor: "transparent", border: "none" }}
            formatter={(value) => fmt(value as number, 0)}
          />
          <Scatter
            name={t.roleDashboards.coo.body.bottlenecksSeries}
            data={data}
            fill="#3b82f6"
            shape="circle"
            opacity={0.6}
          >
            {data.map((entry, index) => (
              <Cell key={index} fill={getConstraintColor(entry.constraint_type)} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Object.entries(t.roleDashboards.coo.body.constraintLabels).map(([type, label]) => (
          <div key={type} className="flex items-center gap-2 text-xs">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: getConstraintColor(type) }}
            />
            <span className="text-muted-foreground">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Theory of Constraints Analysis ────────────────────────────────────────────

interface TOCAnalysisProps {
  processes: ProcessBottleneck[];
}

function TOCAnalysis({ processes }: TOCAnalysisProps) {
  const { t } = useI18n();
  const topConstraints = useMemo(
    () => processes.sort((a, b) => b.impact_score - a.impact_score).slice(0, 5),
    [processes]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingDown className="h-4 w-4" />
        {t.roleDashboards.coo.sections.tocAnalysis}
      </h3>
      <div className="space-y-3">
        {topConstraints.map((proc) => (
          <div key={proc.process_name} className="rounded border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div>
                <p className="font-medium text-sm">{proc.process_name}</p>
                <p className="text-xs text-muted-foreground mt-1">{proc.toc_recommendation}</p>
              </div>
              <span
                className="text-xs px-2 py-1 rounded font-medium text-white shrink-0"
                style={{ backgroundColor: getConstraintColor(proc.constraint_type) }}
              >
                {getConstraintLabel(proc.constraint_type, t.roleDashboards.coo.body.constraintLabels)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{t.roleDashboards.coo.body.impactScore}</span>
              <span className="font-bold">{fmt(proc.impact_score, 0)}/100</span>
            </div>
            <div className="mt-2 w-full bg-muted rounded h-1.5 overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${proc.impact_score}%`,
                  backgroundColor: getConstraintColor(proc.constraint_type),
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── SLA overdue share ─────────────────────────────────────────────────────────

function SLAOverdueCard({ overdue, total }: { overdue: number; total: number }) {
  const { t } = useI18n();
  const rate = total > 0 ? overdue / total : 0;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingDown className="h-4 w-4" />
        {t.roleDashboards.coo.sections.overdueTickets}
      </h3>
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-muted-foreground">
          {t.roleDashboards.coo.body.overdueTicketsLine
            .replace("{overdue}", String(overdue))
            .replace("{total}", String(total))}
        </span>
        <span className={`text-lg font-bold ${rate > 0.1 ? "text-red-400" : "text-green-400"}`}>
          {formatPercent(rate)}
        </span>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {t.roleDashboards.coo.body.trendExplanation}
      </p>
    </div>
  );
}

// ── At-Risk Tickets Table ─────────────────────────────────────────────────────

interface AtRiskTableProps {
  tickets: SLATicket[];
  onSort: (field: string) => void;
}

function AtRiskTicketsTable({ tickets, onSort }: AtRiskTableProps) {
  const { t } = useI18n();
  const atRiskTickets = useMemo(
    () =>
      // Ordered by what is measured — how little SLA time is left. The old
      // sort used a "breach probability" this page invented in the browser
      // (1 - hoursRemaining / 168) and printed as a percentage.
      tickets
        .filter((t) => t.hours_remaining < 48)
        .sort((a, b) => a.hours_remaining - b.hours_remaining),
    [tickets]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <AlertCircle className="h-4 w-4" />
        {t.roleDashboards.coo.sections.atRiskTickets} ({atRiskTickets.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colTicket}</th>
              <th className="text-left py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colTitle}</th>
              <th className="text-left py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colAssigned}</th>
              <th className="text-center py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colRemainingHours}</th>
              <th className="text-center py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colUrgency}</th>
              <th className="text-center py-2 px-2 font-semibold">{t.roleDashboards.coo.body.colPriority}</th>
            </tr>
          </thead>
          <tbody>
            {atRiskTickets.slice(0, 10).map((ticket) => (
              <tr key={ticket.ticket_id} className="border-b border-border hover:bg-muted/30">
                <td className="py-2 px-2 font-mono text-muted-foreground">{ticket.ticket_id}</td>
                <td className="py-2 px-2 truncate">{ticket.title}</td>
                <td className="py-2 px-2 text-muted-foreground">{ticket.assigned_to}</td>
                <td className={`py-2 px-2 text-center font-medium ${ticket.hours_remaining < 24 ? "text-red-400" : ""}`}>
                  {fmt(ticket.hours_remaining, 0)}h
                </td>
                <td className="py-2 px-2 text-center">
                  <span
                    className={`px-2 py-0.5 rounded font-medium ${
                      ticket.hours_remaining <= 0
                        ? "bg-red-500/20 text-red-400"
                        : ticket.hours_remaining < 24
                        ? "bg-yellow-500/20 text-yellow-400"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {ticket.hours_remaining <= 0
                      ? t.roleDashboards.coo.body.timeExpired
                      : ticket.risk_level ?? (ticket.hours_remaining < 24 ? t.roleDashboards.coo.body.near : t.roleDashboards.coo.body.watching)}
                  </span>
                </td>
                <td className="py-2 px-2 text-center">
                  <span className={`px-2 py-0.5 rounded text-white font-medium ${getSeverityColorClass(ticket.priority, true)}`}>
                    {ticket.priority.slice(0, 1).toUpperCase()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function COODashboardPage() {
  const { t } = useI18n();
  const [processCsv, setProcessCsv] = useState("");
  const [slaCsv, setSlaCsv] = useState("");
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [filterPriority, setFilterPriority] = useState<string>("all");

  const { activeCFOJobId, orgId } = useCompanyContextStore();

  const {
    enqueue, reset,
    status, progress, result, logs, error,
    isActive, isEnqueueing,
  } = useAgentJob("coo");

  const [liveResult, setLiveResult] = useState<COOResult | null>(null);

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
        const last = ctx.last_coo_result;
        if (last && typeof last === "object") setLiveResult(last as COOResult);
      } catch {
        /* empty until analyze */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  const cooResult = (result as COOResult | null) ?? liveResult;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!processCsv && !slaCsv) {
      setSubmitError(t.roleDashboards.coo.body.validationError);
      return;
    }
    setSubmitError(null);
    enqueue({
      company_name:     company || undefined,
      reporting_period: period  || undefined,
      process_csv:      processCsv || undefined,
      sla_csv:          slaCsv     || undefined,
    });
  }

  // Parse CSV data
  const parsedProcesses = useMemo(() => {
    if (!processCsv) return [];
    const lines = processCsv.split("\n");
    const headers = lines[0].split(",");
    return lines.slice(1).map((line) => {
      const values = line.split(",");
      return {
        process_name: values[0]?.trim() || "",
        cycle_time: parseFloat(values[1]) || 0,
        throughput: parseFloat(values[2]) || 0,
        wip: parseFloat(values[3]) || 0,
        constraint_type: (values[4]?.trim() as any) || "resource",
        toc_recommendation: "Kısıtlamayı tespit edin ve kapasite artırın",
        impact_score: parseFloat(values[5]) || 50,
      };
    });
  }, [processCsv]);

  const parsedTickets = useMemo(() => {
    if (!slaCsv) return [];
    const lines = slaCsv.split("\n");
    const now = new Date();
    return lines.slice(1).map((line) => {
      const values = line.split(",");
      const dueDate = new Date(values[4]?.trim() || "");
      const hoursRemaining = (dueDate.getTime() - now.getTime()) / (1000 * 3600);
      return {
        ticket_id: values[0]?.trim() || "",
        title: values[1]?.trim() || "",
        assigned_to: values[2]?.trim() || "",
        created_date: values[3]?.trim() || "",
        due_date: values[4]?.trim() || "",
        // Only what the file says: hours left against the due date. This line
        // used to manufacture a "breach probability" from it.
        hours_remaining: hoursRemaining,
        priority: (values[5]?.trim().toLowerCase() as any) || "medium",
        status: values[6]?.trim() || "",
      };
    });
  }, [slaCsv]);

  const displayProcesses = cooResult?.processes?.length ? cooResult.processes : parsedProcesses;
  const displayTickets = cooResult?.sla?.tickets?.length ? cooResult.sla.tickets : parsedTickets;
  const displayOpenTickets = displayTickets.filter(
    (t) => !/^(closed|resolved|kapal|çözül)/i.test(t.status),
  );
  const displayOverdueCount = displayOpenTickets.filter((t) => t.hours_remaining < 0).length;
  const hasResults = Boolean(cooResult || parsedProcesses.length > 0 || parsedTickets.length > 0);

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
      {/* Header */}
      <RoleDashboardHeader
        title={t.roleDashboards.coo.title}
        description={t.roleDashboards.coo.description}
      />

      <DomainPanel
        alan="coo"
        jobId={activeCFOJobId}
        onResult={(r) => setLiveResult(r as unknown as COOResult)}
      />

      {/* Input form */}
      <details open={!hasResults} className="group rounded-xl border border-border/80 bg-card">
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold">{t.roleDashboards.coo.body.csvManualHeading}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <form onSubmit={handleSubmit} className="space-y-4 border-t border-border/80 p-4 sm:p-5">
        {/* Company / Period */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="coo-company" className="mb-1 block text-xs font-medium">
              {t.roleDashboards.coo.body.companyName}
            </label>
            <input
              id="coo-company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="coo-period" className="mb-1 block text-xs font-medium">
              {t.roleDashboards.coo.body.period}
            </label>
            <input
              id="coo-period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q2"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {/* CSV inputs — file drop or paste */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <AgentCsvInput
            label={t.roleDashboards.coo.body.processesCsvLabel}
            value={processCsv}
            onChange={setProcessCsv}
            sampleData={IS_DEMO ? SAMPLE_PROCESSES : undefined}
            description="process_name, cycle_time, throughput, wip, constraint_type, impact_score"
            disabled={isActive || isEnqueueing}
          />
          <AgentCsvInput
            label={t.roleDashboards.coo.body.slaCsvLabel}
            value={slaCsv}
            onChange={setSlaCsv}
            sampleData={IS_DEMO ? SAMPLE_SLA : undefined}
            description="ticket_id, title, assigned_to, created_date, due_date, priority, status"
            disabled={isActive || isEnqueueing}
          />
        </div>

        {submitError && (
          <p role="alert" className="rounded border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-400">
            {submitError}
          </p>
        )}

        <button
          type="submit"
          disabled={isActive || isEnqueueing}
          className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {isActive ? t.roleDashboards.coo.body.analyzing : t.roleDashboards.coo.body.runAnalysis}
        </button>
      </form>
      </details>

      {/* Results */}
      {hasResults && (
        <div className="space-y-6">
          {displayOpenTickets.length > 0 && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <SLAOverdueCard overdue={displayOverdueCount} total={displayOpenTickets.length} />
              <AtRiskTicketsTable tickets={displayTickets} onSort={() => {}} />
            </div>
          )}

          {displayProcesses.length > 0 && (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <BottleneckBubbleChart processes={displayProcesses} />
              <TOCAnalysis processes={displayProcesses} />
            </div>
          )}

          {cooResult?.sla && displayOpenTickets.length === 0 && (
            <SLAOverdueCard overdue={0} total={0} />
          )}
          {cooResult && !cooResult.sla && !cooResult.processes?.length && (
            <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              {t.roleDashboards.coo.body.noResults}
            </p>
          )}
          {cooResult?.error && (
            <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
              {t.roleDashboards.coo.body.errorPrefix} {cooResult.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
