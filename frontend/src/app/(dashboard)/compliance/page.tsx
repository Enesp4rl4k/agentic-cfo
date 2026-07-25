"use client";

import { useState } from "react";
import {
  ShieldCheck, ShieldAlert, AlertTriangle, CheckCircle2,
  XCircle, Clock, FileText, ChevronDown, ChevronUp,
  RefreshCw, Scale, BookOpen,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Cell,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";

interface Alert { level: string; message: string; }
interface Rec { priority: string; action: string; detail: string; effort: string; }

interface PoliciesData {
  total_policies: number; active_policies: number; critical_policies: number;
  policies_needing_review: number;
  review_overdue: { policy: string; days_overdue: number }[];
  alerts: Alert[]; narrative: string;
}

interface ViolationsData {
  total_violations: number; open_violations: number; closed_violations: number;
  overdue_violations: number; critical_open: number; remediation_rate: number;
  avg_days_open: number | null;
  by_severity: Record<string, number>;
  by_framework: Record<string, number>;
  top_overdue: { violation: string; severity: string; owner: string; days_overdue: number; framework: string }[];
  alerts: Alert[]; recommendations: Rec[]; narrative: string;
}

interface RegulationsData {
  total_requirements: number; compliant_count: number; non_compliant_count: number;
  partial_count: number; compliance_coverage_pct: number; frameworks: string[];
  framework_scores: Record<string, number>;
  gaps: { framework: string; requirement: string; status: string; risk: string; owner: string }[];
  audit_overdue_count: number; alerts: Alert[]; recommendations: Rec[]; narrative: string;
}

interface ComplianceSummary {
  overall_health_score: number; health_status: string;
  component_scores: Record<string, number>;
  top_risks: { domain: string; severity: string; message: string }[];
  critical_alert_count: number; warning_alert_count: number;
  recommendations: Rec[]; narrative: string;
}

interface ComplianceResult {
  job_id: string; company_name: string | null;
  policies: PoliciesData | null; violations: ViolationsData | null;
  regulations: RegulationsData | null; compliance_summary: ComplianceSummary | null;
  error: string | null;
}

const LEVEL_STYLE: Record<string, string> = {
  critical: "bg-red-50 text-red-700 ring-red-600/20",
  warning:  "bg-amber-50 text-amber-700 ring-amber-600/20",
  info:     "bg-blue-50 text-blue-700 ring-blue-600/20",
  medium:   "bg-amber-50 text-amber-700 ring-amber-600/20",
};

const SEV_STYLE: Record<string, string> = {
  critical: "bg-red-50 text-red-700 ring-red-600/20",
  high:     "bg-orange-50 text-orange-700 ring-orange-600/20",
  medium:   "bg-amber-50 text-amber-700 ring-amber-600/20",
  low:      "bg-zinc-50 text-zinc-600 ring-zinc-500/10",
};

function Badge({ label, variant = "low" }: { label: string; variant?: string }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset capitalize",
      SEV_STYLE[variant] ?? SEV_STYLE.low,
    )}>
      {label}
    </span>
  );
}

function AlertBadge({ level, message }: Alert) {
  const Icon = level === "critical" ? XCircle : level === "warning" ? AlertTriangle : CheckCircle2;
  return (
    <div className={cn("flex gap-2 rounded-md px-3 py-2 text-sm ring-1 ring-inset", LEVEL_STYLE[level] ?? LEVEL_STYLE.info)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

function ScoreGauge({ score, label }: { score: number; label: string }) {
  const color   = score >= 75 ? "text-emerald-600" : score >= 50 ? "text-amber-600" : "text-red-600";
  const bgColor = score >= 75 ? "bg-emerald-500"   : score >= 50 ? "bg-amber-500"   : "bg-red-500";
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span className={cn("font-semibold", color)}>{score.toFixed(0)}/100</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted">
        <div className={cn("h-2 rounded-full transition-all", bgColor)} style={{ width: `${Math.min(score, 100)}%` }} />
      </div>
    </div>
  );
}

// ── Chart components (shadcn ChartContainer + Recharts) ──────────────────────

const FRAMEWORK_CHART_CONFIG: ChartConfig = {
  score: { label: "Compliance Score", color: "hsl(var(--primary))" },
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high:     "#f97316",
  medium:   "#f59e0b",
  low:      "#6b7280",
};

function FrameworkScoresChart({ scores }: { scores: Record<string, number> }) {
  const data = Object.entries(scores).map(([framework, score]) => ({
    framework: framework.length > 12 ? framework.slice(0, 12) + "\u2026" : framework,
    score: Math.round(score),
    fill: score >= 75 ? "#10b981" : score >= 50 ? "#f59e0b" : "#ef4444",
  }));

  if (data.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Framework Compliance Scores
      </p>
      <ChartContainer config={FRAMEWORK_CHART_CONFIG} className="h-48 w-full">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} tickFormatter={v => `${v}%`} />
          <YAxis type="category" dataKey="framework" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={80} />
          <ChartTooltip content={<ChartTooltipContent formatter={(v) => [`${v}%`, "Score"]} />} />
          <Bar dataKey="score" radius={[0, 4, 4, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  );
}

function ViolationsBySeverityChart({ bySeverity }: { bySeverity: Record<string, number> }) {
  const data = Object.entries(bySeverity)
    .filter(([, v]) => v > 0)
    .map(([severity, count]) => ({ severity, count }));

  if (data.length === 0) return null;

  const config: ChartConfig = Object.fromEntries(
    data.map(({ severity }) => [
      severity,
      { label: severity, color: SEVERITY_COLORS[severity] ?? "#6b7280" },
    ])
  );

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Violations by Severity
      </p>
      <ChartContainer config={config} className="h-40 w-full">
        <BarChart data={data} margin={{ left: 8, right: 8, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="severity" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
          <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} allowDecimals={false} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={SEVERITY_COLORS[entry.severity] ?? "#6b7280"} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  );
}

function HealthBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; icon: typeof ShieldCheck }> = {
    excellent: { cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20", icon: ShieldCheck },
    good:      { cls: "bg-blue-50 text-blue-700 ring-blue-600/20",          icon: ShieldCheck },
    fair:      { cls: "bg-amber-50 text-amber-700 ring-amber-600/20",       icon: ShieldAlert },
    poor:      { cls: "bg-orange-50 text-orange-700 ring-orange-600/20",    icon: ShieldAlert },
    critical:  { cls: "bg-red-50 text-red-700 ring-red-600/20",             icon: XCircle    },
  };
  const cfg  = map[status] ?? map.fair;
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-sm font-medium ring-1 ring-inset capitalize", cfg.cls)}>
      <Icon className="h-4 w-4" aria-hidden="true" />
      {status}
    </span>
  );
}

function Section({
  title, icon: Icon, children, defaultOpen = true,
}: {
  title: string; icon: React.ElementType; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2 font-semibold text-sm">
          <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
          {title}
        </div>
        {open
          ? <ChevronUp   className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          : <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        }
      </button>
      {open && <div className="border-t border-border px-5 py-4">{children}</div>}
    </div>
  );
}

const DEFAULT_POLICY_CSV = `policy,severity,status,last_review,owner,category
Data Classification Policy,high,active,2022-01-15,CISO,data_governance
Access Control Policy,critical,active,2023-06-01,IT Security,security
Incident Response Plan,high,active,2024-01-10,IT Security,security
Password Policy,medium,active,2022-11-20,IT,security
Data Retention Policy,high,active,2021-08-01,Legal,data_governance
Business Continuity Plan,critical,active,2024-02-01,Operations,continuity`;

const DEFAULT_VIOLATIONS_CSV = `violation,policy_id,severity,date_found,due_date,remediation_status,responsible_party,framework
Unencrypted S3 bucket,POL-001,critical,2024-01-10,2024-01-17,open,DevOps,SOC2
Missing MFA on admin accounts,POL-002,critical,2024-02-01,2024-02-08,in progress,IT Security,SOC2
Excessive user privileges,POL-003,high,2024-01-05,2024-02-05,open,IAM Team,ISO27001
Outdated SSL certificate,POL-004,medium,2024-03-01,2024-03-31,resolved,DevOps,PCI-DSS
Missing audit logs,POL-005,high,2023-12-01,2024-01-01,open,Platform,SOC2
Data residency violation,POL-006,critical,2024-02-15,2024-02-22,closed,Data Team,GDPR`;

const DEFAULT_REGULATIONS_CSV = `regulation,requirement,compliance_status,last_audit,next_audit,control_owner,risk_level
SOC2,CC6.1 Logical Access,compliant,2024-01-15,2025-01-15,IT Security,high
SOC2,CC6.2 New User Access,compliant,2024-01-15,2025-01-15,IT Security,high
SOC2,CC7.1 System Monitoring,non-compliant,2024-01-15,2025-01-15,Platform,high
SOC2,CC8.1 Change Management,compliant,2024-01-15,2025-01-15,Engineering,medium
ISO 27001,A.9.1 Access Control Policy,compliant,2023-06-01,2024-06-01,IT Security,high
ISO 27001,A.9.2 User Access Mgmt,partial,2023-06-01,2024-06-01,IT Security,high
GDPR,Article 13 Privacy Notice,compliant,2024-03-01,2025-03-01,Legal,high
GDPR,Article 17 Right to Erasure,non-compliant,2024-03-01,2025-03-01,Data Team,critical`;

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CompliancePage() {
  const [policyCsv,      setPolicyCsv]      = useState(DEFAULT_POLICY_CSV);
  const [violationsCsv,  setViolationsCsv]  = useState(DEFAULT_VIOLATIONS_CSV);
  const [regulationsCsv, setRegulationsCsv] = useState(DEFAULT_REGULATIONS_CSV);
  const [companyName,    setCompanyName]    = useState("");
  const [loading,        setLoading]        = useState(false);
  const [result,         setResult]         = useState<ComplianceResult | null>(null);
  const [error,          setError]          = useState<string | null>(null);

  async function handleAnalyze() {
    setLoading(true); setError(null); setResult(null);
    try {
      const res = await apiClient.post<{ data: ComplianceResult; error: string | null }>(
        "/compliance/analyze",
        {
          company_name:    companyName      || null,
          policy_csv:      policyCsv        || null,
          violations_csv:  violationsCsv    || null,
          regulations_csv: regulationsCsv   || null,
        },
      );
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  const summary    = result?.compliance_summary;
  const policies   = result?.policies;
  const violations = result?.violations;
  const regulations = result?.regulations;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">

      {/* Header */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-primary" aria-hidden="true" />
          <h1 className="text-2xl font-bold tracking-tight">Compliance Dashboard</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          SOC2 · ISO 27001 · GDPR · HIPAA · PCI-DSS — policy inventory, violation tracking, regulatory coverage
        </p>
      </div>

      {/* Input panel */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">Data Input</h2>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="company-name">
              Company Name
            </label>
            <input
              id="company-name"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder="Acme Corp"
              value={companyName}
              onChange={e => setCompanyName(e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {[
            { id: "policy-csv",      label: "Policy CSV",      value: policyCsv,      setter: setPolicyCsv,      hint: "policy, severity, status, last_review, owner, category" },
            { id: "violations-csv",  label: "Violations CSV",  value: violationsCsv,  setter: setViolationsCsv,  hint: "violation, severity, date_found, due_date, remediation_status, responsible_party" },
            { id: "regulations-csv", label: "Regulations CSV", value: regulationsCsv, setter: setRegulationsCsv, hint: "regulation, requirement, compliance_status, last_audit, control_owner, risk_level" },
          ].map(({ id, label, value, setter, hint }) => (
            <div key={id} className="space-y-1">
              <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>
              <p className="text-[10px] text-muted-foreground/70">{hint}</p>
              <textarea
                id={id}
                className="h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                value={value}
                onChange={e => setter(e.target.value)}
                aria-label={label}
              />
            </div>
          ))}
        </div>

        <button
          onClick={handleAnalyze}
          disabled={loading}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {loading
            ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
            : <ShieldCheck className="h-4 w-4"            aria-hidden="true" />}
          {loading ? "Analyzing…" : "Run Compliance Analysis"}
        </button>

        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            <XCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
            {error}
          </div>
        )}
      </div>

      {/* Results */}
      {result && summary && (
        <div className="space-y-4">

          {/* Health summary card */}
          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-3">
                <span className="text-4xl font-bold tabular-nums">{summary.overall_health_score.toFixed(0)}</span>
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Health Score /100</span>
                  <HealthBadge status={summary.health_status} />
                </div>
              </div>
              <div className="flex flex-wrap gap-3 ml-auto text-center">
                {[
                  { label: "Critical Alerts",  value: summary.critical_alert_count, color: summary.critical_alert_count > 0 ? "text-red-600" : "text-emerald-600" },
                  { label: "Warnings",          value: summary.warning_alert_count,  color: "text-amber-600" },
                  { label: "Open Violations",   value: violations?.open_violations ?? "—", color: "text-foreground" },
                  { label: "Reg. Coverage",     value: regulations ? `${regulations.compliance_coverage_pct.toFixed(0)}%` : "—", color: "text-foreground" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="rounded-md border border-border px-4 py-2">
                    <p className={cn("text-xl font-bold", color)}>{value}</p>
                    <p className="text-[11px] text-muted-foreground">{label}</p>
                  </div>
                ))}
              </div>
            </div>

            {Object.keys(summary.component_scores).length > 0 && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {Object.entries(summary.component_scores).map(([k, v]) => (
                  <ScoreGauge key={k} label={k.charAt(0).toUpperCase() + k.slice(1)} score={v} />
                ))}
              </div>
            )}

            {summary.narrative && (
              <p className="text-sm text-muted-foreground border-t border-border pt-3">{summary.narrative}</p>
            )}
          </div>

          {/* Top risks */}
          {summary.top_risks.length > 0 && (
            <Section title="Top Compliance Risks" icon={AlertTriangle}>
              <div className="space-y-2">
                {summary.top_risks.map((r, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-md border border-border p-3">
                    <Badge label={r.severity} variant={r.severity} />
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">{r.domain}</p>
                      <p className="text-sm">{r.message}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Violations */}
          {violations && (
            <Section title={`Violations (${violations.open_violations} open)`} icon={ShieldAlert}>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: "Total",            value: violations.total_violations,                 color: "" },
                    { label: "Open",             value: violations.open_violations,                  color: violations.open_violations > 0 ? "text-amber-600" : "" },
                    { label: "Critical Open",    value: violations.critical_open,                    color: violations.critical_open > 0 ? "text-red-600" : "" },
                    { label: "Remediation Rate", value: `${violations.remediation_rate.toFixed(0)}%`, color: violations.remediation_rate >= 80 ? "text-emerald-600" : "text-amber-600" },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-md border border-border p-3 text-center">
                      <p className={cn("text-2xl font-bold", color)}>{value}</p>
                      <p className="text-xs text-muted-foreground">{label}</p>
                    </div>
                  ))}
                </div>

                {/* Violations by severity chart */}
                {violations.by_severity && Object.keys(violations.by_severity).length > 0 && (
                  <ViolationsBySeverityChart bySeverity={violations.by_severity} />
                )}

                {violations.alerts.map((a, i) => <AlertBadge key={i} {...a} />)}

                {violations.top_overdue.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">Overdue Violations</p>
                    <div className="divide-y divide-border rounded-md border border-border">
                      {violations.top_overdue.map((v, i) => (
                        <div key={i} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                          <Badge label={v.severity} variant={v.severity} />
                          <span className="flex-1 font-medium">{v.violation}</span>
                          <span className="text-muted-foreground text-xs">{v.owner}</span>
                          <span className="text-red-600 text-xs font-medium">{v.days_overdue}d overdue</span>
                          <span className="text-muted-foreground text-xs">{v.framework}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {violations.narrative && <p className="text-sm text-muted-foreground">{violations.narrative}</p>}
              </div>
            </Section>
          )}

          {/* Regulations */}
          {regulations && (
            <Section title={`Regulations (${regulations.compliance_coverage_pct.toFixed(0)}% coverage)`} icon={Scale}>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: "Total Requirements", value: regulations.total_requirements,   color: "" },
                    { label: "Compliant",          value: regulations.compliant_count,      color: "text-emerald-600" },
                    { label: "Non-Compliant",      value: regulations.non_compliant_count,  color: regulations.non_compliant_count > 0 ? "text-red-600" : "" },
                    { label: "Partial",            value: regulations.partial_count,        color: regulations.partial_count > 0 ? "text-amber-600" : "" },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-md border border-border p-3 text-center">
                      <p className={cn("text-2xl font-bold", color)}>{value}</p>
                      <p className="text-xs text-muted-foreground">{label}</p>
                    </div>
                  ))}
                </div>

                {Object.keys(regulations.framework_scores).length > 0 && (
                  <FrameworkScoresChart scores={regulations.framework_scores} />
                )}

                {regulations.alerts.map((a, i) => <AlertBadge key={i} {...a} />)}

                {regulations.gaps.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">Compliance Gaps</p>
                    <div className="divide-y divide-border rounded-md border border-border">
                      {regulations.gaps.map((g, i) => (
                        <div key={i} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                          <Badge label={g.risk}   variant={g.risk} />
                          <Badge label={g.status.replace("_", " ")} variant={g.status === "non_compliant" ? "critical" : "medium"} />
                          <span className="text-xs text-muted-foreground font-mono">{g.framework}</span>
                          <span className="flex-1">{g.requirement}</span>
                          <span className="text-muted-foreground text-xs">{g.owner}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {regulations.narrative && <p className="text-sm text-muted-foreground">{regulations.narrative}</p>}
              </div>
            </Section>
          )}

          {/* Policies */}
          {policies && (
            <Section title={`Policies (${policies.active_policies} active)`} icon={BookOpen} defaultOpen={false}>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: "Total Policies", value: policies.total_policies,            color: "" },
                    { label: "Active",         value: policies.active_policies,           color: "text-emerald-600" },
                    { label: "Critical/High",  value: policies.critical_policies,         color: policies.critical_policies > 0 ? "text-amber-600" : "" },
                    { label: "Needs Review",   value: policies.policies_needing_review,   color: policies.policies_needing_review > 0 ? "text-red-600" : "" },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-md border border-border p-3 text-center">
                      <p className={cn("text-2xl font-bold", color)}>{value}</p>
                      <p className="text-xs text-muted-foreground">{label}</p>
                    </div>
                  ))}
                </div>

                {policies.alerts.map((a, i) => <AlertBadge key={i} {...a} />)}

                {policies.review_overdue.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">Overdue Reviews</p>
                    <div className="divide-y divide-border rounded-md border border-border">
                      {policies.review_overdue.map((p, i) => (
                        <div key={i} className="flex items-center gap-2 px-3 py-2 text-sm">
                          <Clock className="h-3 w-3 text-amber-600 shrink-0" aria-hidden="true" />
                          <span className="flex-1">{p.policy}</span>
                          <span className="text-muted-foreground text-xs">{p.days_overdue}d overdue</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {policies.narrative && <p className="text-sm text-muted-foreground">{policies.narrative}</p>}
              </div>
            </Section>
          )}

          {/* Recommendations */}
          {summary.recommendations.length > 0 && (
            <Section title="Actionable Recommendations" icon={FileText}>
              <div className="space-y-3">
                {summary.recommendations.map((r, i) => (
                  <div key={i} className="rounded-md border border-border p-4 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge label={r.priority} variant={r.priority === "P1" ? "critical" : r.priority === "P2" ? "high" : "low"} />
                      <span className="text-sm font-medium">{r.action}</span>
                      <Badge label={`effort: ${r.effort}`} variant="low" />
                    </div>
                    <p className="text-xs text-muted-foreground pl-1">{r.detail}</p>
                  </div>
                ))}
              </div>
            </Section>
          )}

        </div>
      )}
    </div>
  );
}
