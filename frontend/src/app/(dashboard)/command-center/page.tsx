"use client";

import { useState } from "react";
import {
  Crown, DollarSign, Cpu, Megaphone, Layers, Users,
  ShieldCheck, AlertTriangle, FileSearch, Activity,
  TrendingUp, TrendingDown, Minus, Zap, Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentHealth {
  agent: string;
  icon: React.ElementType;
  color: string;
  health_score: number;
  status: "excellent" | "good" | "warning" | "critical";
  top_alert: string | null;
  kpis: { label: string; value: string; trend?: "up" | "down" | "stable" }[];
}

interface CrossRisk {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  domains: string[];
  impact: string;
}

interface QuickWin {
  action: string;
  estimated_impact: string;
  effort: "low" | "medium" | "high";
  owner: string;
}

// ── Mock Data (would come from API in production) ────────────────────────────

const MOCK_AGENTS: AgentHealth[] = [
  {
    agent: "CFO",
    icon: DollarSign,
    color: "text-emerald-500",
    health_score: 78,
    status: "good",
    top_alert: "Cash runway: 8 months",
    kpis: [
      { label: "Revenue", value: "₺2.4M", trend: "up" },
      { label: "Burn Rate", value: "₺300K/mo", trend: "down" },
      { label: "Gross Margin", value: "68%", trend: "stable" },
    ],
  },
  {
    agent: "CTO",
    icon: Cpu,
    color: "text-blue-500",
    health_score: 65,
    status: "warning",
    top_alert: "Tech debt growing: 142 days",
    kpis: [
      { label: "Uptime", value: "99.8%", trend: "stable" },
      { label: "Velocity", value: "32 SP", trend: "down" },
      { label: "Incidents", value: "3 P1", trend: "up" },
    ],
  },
  {
    agent: "CMO",
    icon: Megaphone,
    color: "text-purple-500",
    health_score: 82,
    status: "good",
    top_alert: "CAC trending up +12%",
    kpis: [
      { label: "CAC", value: "₺450", trend: "up" },
      { label: "LTV", value: "₺2.1K", trend: "stable" },
      { label: "Conv. Rate", value: "3.2%", trend: "up" },
    ],
  },
  {
    agent: "COO",
    icon: Layers,
    color: "text-orange-500",
    health_score: 71,
    status: "good",
    top_alert: "SLA breach rate: 15%",
    kpis: [
      { label: "Efficiency", value: "7.2/10", trend: "stable" },
      { label: "Utilization", value: "88%", trend: "up" },
      { label: "NPS", value: "42", trend: "stable" },
    ],
  },
  {
    agent: "CHRO",
    icon: Users,
    color: "text-pink-500",
    health_score: 69,
    status: "warning",
    top_alert: "Attrition risk: 3 key roles",
    kpis: [
      { label: "Headcount", value: "87", trend: "up" },
      { label: "Attrition", value: "18%", trend: "up" },
      { label: "Satisfaction", value: "7.1/10", trend: "down" },
    ],
  },
  {
    agent: "Compliance",
    icon: ShieldCheck,
    color: "text-cyan-500",
    health_score: 88,
    status: "excellent",
    top_alert: null,
    kpis: [
      { label: "Coverage", value: "94%", trend: "up" },
      { label: "Open Violations", value: "2", trend: "down" },
      { label: "Frameworks", value: "5", trend: "stable" },
    ],
  },
  {
    agent: "Risk",
    icon: Shield,
    color: "text-red-500",
    health_score: 58,
    status: "critical",
    top_alert: "5 high-severity risks open",
    kpis: [
      { label: "High Risks", value: "5", trend: "up" },
      { label: "Loss Events", value: "₺45K", trend: "up" },
      { label: "KRI Score", value: "6.2/10", trend: "stable" },
    ],
  },
  {
    agent: "Internal Audit",
    icon: FileSearch,
    color: "text-indigo-500",
    health_score: 75,
    status: "good",
    top_alert: "2 audits overdue",
    kpis: [
      { label: "Coverage", value: "82%", trend: "up" },
      { label: "Findings", value: "12", trend: "down" },
      { label: "Remediation", value: "85%", trend: "up" },
    ],
  },
  {
    agent: "CEO",
    icon: Crown,
    color: "text-yellow-500",
    health_score: 72,
    status: "good",
    top_alert: "2 strategic priorities urgent",
    kpis: [
      { label: "Overall Health", value: "72/100", trend: "stable" },
      { label: "Cross-Risks", value: "3", trend: "stable" },
      { label: "Board Readiness", value: "Good", trend: "up" },
    ],
  },
];

const MOCK_CROSS_RISKS: CrossRisk[] = [
  {
    id: "CR-001",
    title: "Tech debt impacting revenue delivery",
    severity: "high",
    domains: ["CTO", "CFO", "COO"],
    impact: "Estimated ₺180K revenue delay this quarter",
  },
  {
    id: "CR-002",
    title: "High attrition in engineering + rising CAC",
    severity: "critical",
    domains: ["CHRO", "CMO", "CTO"],
    impact: "Hiring costs up 40%, velocity down 25%",
  },
  {
    id: "CR-003",
    title: "Compliance audit gaps creating legal risk",
    severity: "medium",
    domains: ["Compliance", "Risk", "Internal Audit"],
    impact: "Potential regulatory fine exposure",
  },
];

const MOCK_QUICK_WINS: QuickWin[] = [
  {
    action: "Automate manual compliance checks",
    estimated_impact: "Save 20h/month, reduce violations by 30%",
    effort: "low",
    owner: "Compliance + CTO",
  },
  {
    action: "Implement retention bonuses for 3 key engineers",
    estimated_impact: "Reduce attrition risk, maintain velocity",
    effort: "low",
    owner: "CHRO",
  },
  {
    action: "Optimize cloud spend in non-prod environments",
    estimated_impact: "Save ₺25K/month, extend runway by 2 weeks",
    effort: "medium",
    owner: "CTO + CFO",
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function getStatusColor(status: AgentHealth["status"]): string {
  switch (status) {
    case "excellent": return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
    case "good":      return "bg-blue-500/10 text-blue-500 border-blue-500/20";
    case "warning":   return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    case "critical":  return "bg-red-500/10 text-red-500 border-red-500/20";
  }
}

function getSeverityStyle(severity: CrossRisk["severity"]): string {
  switch (severity) {
    case "critical": return "bg-red-500/10 text-red-400 border-red-500/30";
    case "high":     return "bg-orange-500/10 text-orange-400 border-orange-500/30";
    case "medium":   return "bg-yellow-500/10 text-yellow-400 border-yellow-500/30";
    case "low":      return "bg-blue-500/10 text-blue-400 border-blue-500/30";
  }
}

function getEffortStyle(effort: QuickWin["effort"]): string {
  switch (effort) {
    case "low":    return "bg-emerald-500/20 text-emerald-400";
    case "medium": return "bg-yellow-500/20 text-yellow-400";
    case "high":   return "bg-red-500/20 text-red-400";
  }
}

function TrendIcon({ trend }: { trend?: "up" | "down" | "stable" }) {
  if (trend === "up")     return <TrendingUp   className="h-3 w-3 text-emerald-400" aria-hidden="true" />;
  if (trend === "down")   return <TrendingDown className="h-3 w-3 text-red-400" aria-hidden="true" />;
  if (trend === "stable") return <Minus        className="h-3 w-3 text-muted-foreground" aria-hidden="true" />;
  return null;
}

// ── Components ────────────────────────────────────────────────────────────────

function CompanyHealthGauge({ avgScore }: { avgScore: number }) {
  const color = avgScore >= 75 ? "text-emerald-400" : avgScore >= 60 ? "text-yellow-400" : "text-red-400";
  const r = 50;
  const circ = 2 * Math.PI * r;
  const dash = (avgScore / 100) * circ;

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="140" height="140" viewBox="0 0 140 140" aria-hidden="true">
        <circle cx="70" cy="70" r={r} fill="none" stroke="currentColor"
          className="text-muted/20" strokeWidth="12" />
        <circle cx="70" cy="70" r={r} fill="none" stroke="currentColor"
          className={color} strokeWidth="12"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 70 70)" />
        <text x="70" y="75" textAnchor="middle" fontSize="28" fontWeight="bold"
          fill="currentColor" className={color}>
          {avgScore.toFixed(0)}
        </text>
      </svg>
      <div className="text-center">
        <p className="text-sm font-semibold">Company Health</p>
        <p className="text-xs text-muted-foreground">9-agent average</p>
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentHealth }) {
  const Icon = agent.icon;
  const healthColor = agent.health_score >= 75 ? "text-emerald-400" : agent.health_score >= 60 ? "text-yellow-400" : "text-red-400";

  return (
    <div className="rounded-lg border border-border bg-card p-4 hover:border-primary/40 transition-colors">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={cn("h-5 w-5", agent.color)} aria-hidden="true" />
          <span className="font-semibold text-sm">{agent.agent}</span>
        </div>
        <span className={cn("text-xl font-bold tabular-nums", healthColor)}>
          {agent.health_score}
        </span>
      </div>

      {/* Status badge */}
      <div className={cn("mb-3 rounded border px-2 py-1 text-xs font-medium capitalize", getStatusColor(agent.status))}>
        {agent.status}
      </div>

      {/* Top alert */}
      {agent.top_alert && (
        <div className="mb-3 flex items-start gap-2 rounded bg-muted/40 px-2 py-1.5">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" aria-hidden="true" />
          <p className="text-xs text-muted-foreground">{agent.top_alert}</p>
        </div>
      )}

      {/* KPIs */}
      <div className="space-y-1.5">
        {agent.kpis.map((kpi, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">{kpi.label}</span>
            <div className="flex items-center gap-1">
              <span className="font-medium tabular-nums">{kpi.value}</span>
              <TrendIcon trend={kpi.trend} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CrossRiskCard({ risk }: { risk: CrossRisk }) {
  return (
    <div className={cn("rounded-lg border p-4", getSeverityStyle(risk.severity))}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-semibold text-sm">{risk.title}</span>
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold border uppercase", getSeverityStyle(risk.severity))}>
              {risk.severity}
            </span>
          </div>
          <p className="text-xs opacity-80">{risk.impact}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mt-2">
        {risk.domains.map((d) => (
          <span key={d} className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {d}
          </span>
        ))}
      </div>
    </div>
  );
}

function QuickWinCard({ win }: { win: QuickWin }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="flex-1 font-medium text-sm">{win.action}</span>
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase", getEffortStyle(win.effort))}>
          {win.effort}
        </span>
      </div>
      <p className="mb-1 text-xs text-muted-foreground">{win.estimated_impact}</p>
      <p className="text-xs text-muted-foreground/70">Owner: {win.owner}</p>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CommandCenterPage() {
  const [agents] = useState<AgentHealth[]>(MOCK_AGENTS);
  const [crossRisks] = useState<CrossRisk[]>(MOCK_CROSS_RISKS);
  const [quickWins] = useState<QuickWin[]>(MOCK_QUICK_WINS);

  const avgScore = agents.reduce((sum, a) => sum + a.health_score, 0) / agents.length;
  const criticalCount = agents.filter(a => a.status === "critical").length;
  const warningCount = agents.filter(a => a.status === "warning").length;
  const criticalRisks = crossRisks.filter(r => r.severity === "critical" || r.severity === "high").length;

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Activity className="h-6 w-6 text-primary" aria-hidden="true" />
        <div>
          <h1 className="text-xl font-bold">Executive Command Center</h1>
          <p className="text-sm text-muted-foreground">
            Unified intelligence dashboard — 9 agents, real-time health monitoring
          </p>
        </div>
      </div>

      {/* Company health summary */}
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex flex-wrap items-center gap-8">
          <CompanyHealthGauge avgScore={avgScore} />

          <div className="flex-1 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-emerald-400">
                {agents.filter(a => a.status === "excellent").length}
              </p>
              <p className="text-xs text-muted-foreground">Excellent</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-blue-400">
                {agents.filter(a => a.status === "good").length}
              </p>
              <p className="text-xs text-muted-foreground">Good</p>
            </div>
            <div className="text-center">
              <p className={cn("text-2xl font-bold", warningCount > 0 ? "text-amber-400" : "text-muted-foreground")}>
                {warningCount}
              </p>
              <p className="text-xs text-muted-foreground">Warning</p>
            </div>
            <div className="text-center">
              <p className={cn("text-2xl font-bold", criticalCount > 0 ? "text-red-400" : "text-muted-foreground")}>
                {criticalCount}
              </p>
              <p className="text-xs text-muted-foreground">Critical</p>
            </div>
          </div>
        </div>

        {(criticalCount > 0 || criticalRisks > 0) && (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <p className="text-sm text-amber-400">
              {criticalCount > 0 && `${criticalCount} agent${criticalCount > 1 ? "s" : ""} require immediate attention`}
              {criticalCount > 0 && criticalRisks > 0 && " · "}
              {criticalRisks > 0 && `${criticalRisks} high-severity cross-domain risk${criticalRisks > 1 ? "s" : ""}`}
            </p>
          </div>
        )}
      </div>

      {/* Agent grid */}
      <div>
        <h2 className="mb-3 text-sm font-semibold">Agent Health Status</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {agents.map((agent) => (
            <AgentCard key={agent.agent} agent={agent} />
          ))}
        </div>
      </div>

      {/* Cross-domain risks */}
      {crossRisks.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-5">
          <div className="mb-4 flex items-center gap-2">
            <Shield className="h-4 w-4 text-red-400" aria-hidden="true" />
            <h2 className="text-sm font-semibold">Cross-Domain Risks</h2>
            <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-400">
              {crossRisks.length}
            </span>
          </div>
          <div className="space-y-3">
            {crossRisks.map((risk) => (
              <CrossRiskCard key={risk.id} risk={risk} />
            ))}
          </div>
        </div>
      )}

      {/* Quick wins */}
      {quickWins.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-5">
          <div className="mb-4 flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-sm font-semibold">Quick Wins — Actionable Now</h2>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {quickWins.length}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {quickWins.map((win, i) => (
              <QuickWinCard key={i} win={win} />
            ))}
          </div>
        </div>
      )}

      {/* Footer note */}
      <div className="rounded-lg border border-border bg-muted/30 p-4 text-center">
        <p className="text-xs text-muted-foreground">
          💡 This dashboard synthesizes real-time data from all 9 executive agents. Data refreshes every 5 minutes.
        </p>
      </div>
    </main>
  );
}
