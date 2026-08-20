"use client";

import { type ElementType } from "react";
import { useSearchParams } from "next/navigation";
import {
  Crown, DollarSign, Cpu, Megaphone, Layers, Users,
  ShieldCheck, AlertTriangle, FileSearch, Activity,
  TrendingUp, TrendingDown, Minus, Zap, Shield, RefreshCw, AlertCircle,
  Building2, CheckCircle2, Loader2, ChevronRight,
} from "lucide-react";
import { FileDown, Loader2 as Loader } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { useCommandCenter } from "@/hooks/useCFO";
import { useContextSummary, useActiveCFOJob, useFullContext } from "@/hooks/useCompanyContext";
import { useSystemHealth, useSystemOps } from "@/hooks/useSystemOps";
import { apiClient } from "@/lib/api/client";
import { CrossAgentIntelligence } from "@/components/ui/cross-agent-intelligence";
import { ConflictCard } from "@/components/command-center/ConflictCard";
import type { AgentHealthItem, CrossRiskItem, QuickWinItem } from "@/lib/api/cfo";
import type { ContextSummary } from "@/lib/api/context";

// ── Types (re-use API types, add icon/color locally) ──────────────────────────

type AgentHealth = AgentHealthItem & {
  icon: ElementType;
  color: string;
};

// Map agent names → icons + colors (fallback for any new agent names)
const AGENT_META: Record<string, { icon: ElementType; color: string }> = {
  CFO:             { icon: DollarSign,  color: "text-emerald-500" },
  CEO:             { icon: Crown,       color: "text-yellow-500" },
  CTO:             { icon: Cpu,         color: "text-blue-500" },
  CMO:             { icon: Megaphone,   color: "text-purple-500" },
  COO:             { icon: Layers,      color: "text-orange-500" },
  CHRO:            { icon: Users,       color: "text-pink-500" },
  Compliance:      { icon: ShieldCheck, color: "text-cyan-500" },
  Risk:            { icon: Shield,      color: "text-red-500" },
  "Internal Audit":{ icon: FileSearch,  color: "text-indigo-500" },
};

const DEFAULT_META = { icon: Activity, color: "text-muted-foreground" };

function enrichAgent(a: AgentHealthItem): AgentHealth {
  const meta = AGENT_META[a.agent] ?? DEFAULT_META;
  return { ...a, ...meta };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getStatusColor(status: AgentHealth["status"]): string {
  switch (status) {
    case "excellent": return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
    case "good":      return "bg-blue-500/10 text-blue-500 border-blue-500/20";
    case "warning":   return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    case "critical":  return "bg-red-500/10 text-red-500 border-red-500/20";
  }
}

function getSeverityStyle(severity: CrossRiskItem["severity"]): string {
  switch (severity) {
    case "critical": return "bg-red-500/10 text-red-400 border-red-500/30";
    case "high":     return "bg-orange-500/10 text-orange-400 border-orange-500/30";
    case "medium":   return "bg-yellow-500/10 text-yellow-400 border-yellow-500/30";
    case "low":      return "bg-blue-500/10 text-blue-400 border-blue-500/30";
    default:         return "bg-muted text-muted-foreground border-border";
  }
}

function getEffortStyle(effort: QuickWinItem["effort"]): string {
  switch (effort) {
    case "low":    return "bg-emerald-500/20 text-emerald-400";
    case "medium": return "bg-yellow-500/20 text-yellow-400";
    case "high":   return "bg-red-500/20 text-red-400";
    default:       return "bg-muted text-muted-foreground";
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

function CrossRiskCard({ risk }: { risk: CrossRiskItem }) {
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

function QuickWinCard({ win }: { win: QuickWinItem }) {
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

function ManagementLayerCard() {
  const { data: health } = useSystemHealth();
  const { data: ops } = useSystemOps();
  const activeCfoJobId = useActiveCFOJob();
  const [deckBusy, setDeckBusy] = useState(false);
  const [deckMsg, setDeckMsg] = useState<string | null>(null);

  const statusBadge = health?.ok
    ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
    : "bg-amber-500/15 text-amber-400 border-amber-500/30";

  const failed = ops?.jobs.recent_failed ?? [];
  const awaitingReview = ops?.jobs.awaiting_review ?? 0;
  const completedCount = ops?.jobs.status_counts?.completed ?? 0;
  const failedCount = ops?.jobs.status_counts?.failed ?? 0;
  const breaches = ops?.sla.breaches ?? [];
  const hasEscalation = breaches.length > 0 || failedCount > 0;
  const suggestedActions = ops?.suggested_actions ?? [];
  const openConflicts = ops?.management?.open_conflicts ?? 0;

  async function generateBoardDeck() {
    if (!activeCfoJobId) {
      setDeckMsg("Aktif CFO job yok — önce upload/analiz çalıştırın.");
      return;
    }
    setDeckBusy(true);
    setDeckMsg(null);
    try {
      const res = await apiClient.post(`/ceo/analyze-from-job/${activeCfoJobId}`, {});
      const data = (res.data as { data?: { board_deck?: unknown }; board_deck?: unknown })?.data
        ?? res.data;
      if ((data as { board_deck?: unknown })?.board_deck) {
        setDeckMsg("Board deck üretildi — CEO sayfasından görüntüleyin.");
      } else {
        setDeckMsg("CEO sentezi tetiklendi.");
      }
    } catch (err) {
      setDeckMsg(err instanceof Error ? err.message : "Board deck oluşturulamadı");
    } finally {
      setDeckBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Management Layer v1.5</h2>
        </div>
        <span className={cn("rounded border px-2 py-0.5 text-xs font-medium", statusBadge)}>
          {health?.status ?? "checking"}
        </span>
      </div>
      {hasEscalation && (
        <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <p className="text-xs font-medium text-amber-300">Escalation Active</p>
          <p className="text-[11px] text-amber-200/80">
            {breaches.length > 0
              ? `${breaches.length} SLA breach detected`
              : "Recent failures require operator review"}
            {openConflicts > 0 ? ` · ${openConflicts} open agent conflicts` : ""}
          </p>
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={deckBusy || !activeCfoJobId}
          onClick={() => void generateBoardDeck()}
          className="inline-flex items-center gap-2 rounded border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-50"
        >
          {deckBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileDown className="h-3 w-3" />}
          Generate board deck
        </button>
        {deckMsg && <p className="w-full text-[11px] text-muted-foreground">{deckMsg}</p>}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded border border-border bg-muted/20 p-2">
          <p className="text-[10px] text-muted-foreground">Completed Jobs</p>
          <p className="text-base font-semibold text-emerald-400">{completedCount}</p>
        </div>
        <div className="rounded border border-border bg-muted/20 p-2">
          <p className="text-[10px] text-muted-foreground">Failed Jobs</p>
          <p className="text-base font-semibold text-red-400">{failedCount}</p>
        </div>
        <div className="rounded border border-border bg-muted/20 p-2">
          <p className="text-[10px] text-muted-foreground">Awaiting Review</p>
          <p className={cn("text-base font-semibold", awaitingReview > 0 ? "text-amber-400" : "text-muted-foreground")}>
            {awaitingReview}
          </p>
        </div>
        <div className="rounded border border-border bg-muted/20 p-2">
          <p className="text-[10px] text-muted-foreground">Queue Depth</p>
          <p className="text-base font-semibold text-blue-400">
            {typeof ops?.sla.queue_depth === "number" ? ops.sla.queue_depth : "n/a"}
          </p>
        </div>
        <div className="rounded border border-border bg-muted/20 p-2 col-span-2 sm:col-span-4">
          <p className="text-[10px] text-muted-foreground">SLA (P95)</p>
          <p className="text-xs text-muted-foreground">
            completion: {ops?.sla.job_completion_p95_ms ? `${Math.round(ops.sla.job_completion_p95_ms / 1000)}s` : "n/a"} ·
            first-result: {ops?.sla.time_to_first_result_p95_ms ? `${Math.round(ops.sla.time_to_first_result_p95_ms / 1000)}s` : "n/a"}
          </p>
        </div>
      </div>

      <div className="mb-4">
        <p className="mb-2 text-xs font-medium text-muted-foreground">SLA Breaches</p>
        {breaches.length === 0 ? (
          <p className="rounded border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            No active SLA breaches.
          </p>
        ) : (
          <div className="space-y-2">
            {breaches.slice(0, 3).map((b) => (
              <div key={b.job_id} className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
                <p className="text-xs font-medium text-amber-200">{b.job_id}</p>
                <p className="text-[11px] text-amber-100/80">
                  {b.status} for {b.age_minutes}m (threshold {b.threshold_minutes}m)
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Recent Failures</p>
        {failed.length === 0 ? (
          <p className="rounded border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            No failed jobs in recent window.
          </p>
        ) : (
          <div className="space-y-2">
            {failed.slice(0, 3).map((f) => (
              <div key={f.job_id} className="rounded border border-red-500/20 bg-red-500/5 px-3 py-2">
                <p className="text-xs font-medium text-red-300">{f.job_id}</p>
                <p className="text-[11px] text-red-200/80">{f.error_message || "Unknown error"}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium text-muted-foreground">Suggested Actions</p>
        <ul className="space-y-1">
          {suggestedActions.map((action, idx) => (
            <li key={`${idx}-${action}`} className="rounded border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
              {action}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ── Auto-Chain Pipeline Status ────────────────────────────────────────────────
// Shows which agents have run, are running, or are waiting based on CompanyContext

interface PipelineNode {
  key: string;
  label: string;
  icon: ElementType;
  color: string;
  triggers?: string[]; // keys of agents this one triggers
}

const PIPELINE_NODES: PipelineNode[] = [
  { key: "cfo",        label: "CFO",          icon: DollarSign,  color: "text-emerald-400", triggers: ["risk", "audit"] },
  { key: "risk",       label: "Risk",         icon: Shield,      color: "text-red-400",     triggers: ["compliance"] },
  { key: "audit",      label: "Audit",        icon: FileSearch,  color: "text-indigo-400" },
  { key: "compliance", label: "Compliance",   icon: ShieldCheck, color: "text-cyan-400" },
  { key: "cto",        label: "CTO",          icon: Cpu,         color: "text-blue-400" },
  { key: "cmo",        label: "CMO",          icon: Megaphone,   color: "text-purple-400" },
  { key: "coo",        label: "COO",          icon: Layers,      color: "text-orange-400" },
  { key: "chro",       label: "CHRO",         icon: Users,       color: "text-pink-400" },
  { key: "ceo",        label: "CEO Synthesis",icon: Crown,       color: "text-yellow-400" },
];

// Auto-chain groups: first row = CFO chain, second row = manual agents, third = synthesis
const CHAIN_ROWS: PipelineNode[][] = [
  [
    PIPELINE_NODES[0], // CFO
    PIPELINE_NODES[1], // Risk
    PIPELINE_NODES[2], // Audit
    PIPELINE_NODES[3], // Compliance
  ],
  [
    PIPELINE_NODES[4], // CTO
    PIPELINE_NODES[5], // CMO
    PIPELINE_NODES[6], // COO
    PIPELINE_NODES[7], // CHRO
  ],
  [
    PIPELINE_NODES[8], // CEO Synthesis
  ],
];

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "az önce";
  if (mins < 60) return `${mins}dk önce`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}sa önce`;
  return `${Math.floor(hrs / 24)}g önce`;
}

function PipelineNodeCard({
  node,
  hasResult,
  isActive,
  updatedAt,
}: {
  node: PipelineNode;
  hasResult: boolean;
  isActive: boolean;
  updatedAt?: string | undefined;
}) {
  const Icon = node.icon;

  const stateClass = isActive
    ? "border-primary/50 bg-primary/5"
    : hasResult
    ? "border-emerald-500/30 bg-emerald-950/20"
    : "border-border bg-card opacity-60";

  const iconClass = isActive
    ? "text-primary"
    : hasResult
    ? node.color
    : "text-muted-foreground";

  return (
    <div className={cn("flex flex-col items-center gap-1.5 rounded-lg border px-3 py-2.5 text-center transition-all min-w-[80px]", stateClass)}>
      <div className="relative">
        <Icon className={cn("h-5 w-5", iconClass)} aria-hidden="true" />
        {isActive && (
          <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-primary animate-pulse" aria-hidden="true" />
        )}
        {hasResult && !isActive && (
          <CheckCircle2 className="absolute -right-1.5 -top-1.5 h-3 w-3 text-emerald-400" aria-hidden="true" />
        )}
      </div>
      <span className="text-[10px] font-semibold leading-tight">{node.label}</span>
      {isActive && (
        <span className="flex items-center gap-0.5 text-[9px] text-primary">
          <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
          çalışıyor
        </span>
      )}
      {hasResult && !isActive && updatedAt && (
        <span className="text-[9px] text-muted-foreground">{relativeTime(updatedAt)}</span>
      )}
      {!hasResult && !isActive && (
        <span className="text-[9px] text-muted-foreground">bekliyor</span>
      )}
    </div>
  );
}

function AgentPipelineStatus({ summary }: { summary: ContextSummary }) {
  const agents = summary.agents ?? {};
  const activeJobs = summary.active_jobs ?? {};

  const getNode = (key: string) => {
    const status = agents[key];
    const isActive = !!(activeJobs[key]);
    return {
      hasResult: status?.has_result ?? false,
      isActive,
      updatedAt: status?.updated_at,
    };
  };

  const totalDone = Object.values(agents).filter((a) => a.has_result).length;
  const totalActive = Object.values(activeJobs).filter(Boolean).length;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-sm font-semibold">Auto-Chain Pipeline</h2>
          {totalActive > 0 && (
            <span className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              <Loader2 className="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
              {totalActive} çalışıyor
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {totalDone} / {PIPELINE_NODES.length} tamamlandı
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all duration-700"
          style={{ width: `${(totalDone / PIPELINE_NODES.length) * 100}%` }}
          aria-label={`${totalDone} of ${PIPELINE_NODES.length} agents completed`}
        />
      </div>

      {/* CFO auto-chain row */}
      <div className="mb-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          CFO Auto-Chain
        </p>
        <div className="flex items-center gap-1 flex-wrap">
          {CHAIN_ROWS[0].map((node, i) => {
            const state = getNode(node.key);
            return (
              <div key={node.key} className="flex items-center gap-1">
                <PipelineNodeCard node={node} {...state} />
                {i < CHAIN_ROWS[0].length - 1 && (
                  <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/40" aria-hidden="true" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Manual agents row */}
      <div className="mb-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Domain Analizleri
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          {CHAIN_ROWS[1].map((node) => {
            const state = getNode(node.key);
            return <PipelineNodeCard key={node.key} node={node} {...state} />;
          })}
        </div>
      </div>

      {/* CEO synthesis */}
      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          CEO Sentezi
        </p>
        <div className="flex items-center gap-2">
          {CHAIN_ROWS[2].map((node) => {
            const state = getNode(node.key);
            return <PipelineNodeCard key={node.key} node={node} {...state} />;
          })}
          {getNode("ceo").hasResult && (
            <div className="flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              Board deck hazır
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function CommandCenterSkeleton() {
  return (
    <div className="space-y-6 p-4 sm:p-6 lg:p-8" aria-busy="true" aria-label="Loading Command Center">
      <div className="h-8 w-64 animate-pulse rounded bg-muted" />
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex flex-wrap items-center gap-8">
          <div className="h-36 w-36 animate-pulse rounded-full bg-muted" />
          <div className="flex-1 grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-12 animate-pulse rounded bg-muted" />
            ))}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {[...Array(9)].map((_, i) => (
          <div key={i} className="h-48 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}

// ── Download Board Deck Button ────────────────────────────────────────────────

function DownloadBoardDeckButton() {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      const res = await apiClient.get("/reports/unified/pdf", {
        responseType: "blob",
      });
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `yonetim-raporu-${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError("PDF indirilemedi. Önce analiz çalıştırın.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={handleDownload}
        disabled={downloading}
        aria-label="Board Deck PDF indir"
        className={cn(
          "flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground",
          "hover:opacity-90 transition-state press-feedback disabled:opacity-50"
        )}
      >
        {downloading
          ? <><Loader className="h-3 w-3 animate-spin" aria-hidden="true" />İndiriliyor…</>
          : <><FileDown className="h-3 w-3" aria-hidden="true" />Board Deck İndir</>
        }
      </button>
      {error && (
        <p className="text-[10px] text-destructive max-w-[160px] text-right">{error}</p>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function CommandCenterPage() {
  const searchParams = useSearchParams();
  const urlJobId = searchParams.get("job");

  // Use context job ID as fallback when URL param is absent
  const contextJobId = useActiveCFOJob();
  const jobId = urlJobId ?? contextJobId;

  // Context summary — which agents have run, company name
  const { data: ctxSummary } = useContextSummary();

  // Full context — for cross-agent intelligence
  const { data: fullCtx } = useFullContext();

  const { data, isLoading, isError, refetch, isFetching } = useCommandCenter(jobId);

  // Enrich API agents with icons/colors
  const agents: AgentHealth[] = (data?.agents ?? []).map(enrichAgent);
  const crossRisks: CrossRiskItem[] = data?.cross_risks ?? [];
  const quickWins: QuickWinItem[] = data?.quick_wins ?? [];

  const avgScore = agents.length
    ? agents.reduce((sum, a) => sum + a.health_score, 0) / agents.length
    : 0;
  const criticalCount = agents.filter(a => a.status === "critical").length;
  const warningCount = agents.filter(a => a.status === "warning").length;
  const criticalRisks = crossRisks.filter(r => r.severity === "critical" || r.severity === "high").length;

  if (isLoading) return <CommandCenterSkeleton />;

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
        <div className="mb-4 rounded-full bg-destructive/10 p-4">
          <AlertCircle className="h-8 w-8 text-destructive" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">Analysis failed</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
          Could not load Command Center data. Make sure the backend is running.
        </p>
        <button
          onClick={() => refetch()}
          className="mt-5 flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Retry
        </button>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Activity className="h-6 w-6 text-primary" aria-hidden="true" />
          <div>
            <h1 className="text-xl font-bold">Executive Command Center</h1>
            <p className="text-sm text-muted-foreground">
              {ctxSummary?.company_name
                ? <><Building2 className="inline h-3.5 w-3.5 mr-1 opacity-60" aria-hidden="true" />{ctxSummary.company_name} · </>
                : null}
              Agentic Management OS · {agents.length || 9} agents · real-time health
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          aria-label="Refresh Command Center"
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={cn("h-3 w-3", isFetching && "animate-spin")} aria-hidden="true" />
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>

        {/* Unified PDF Export */}
        <DownloadBoardDeckButton />
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

      {/* Auto-chain pipeline status */}
      {ctxSummary && (
        <AgentPipelineStatus summary={ctxSummary} />
      )}

      {/* Unified management visibility (ops + reliability) */}
      <ManagementLayerCard />

      {/* Cross-agent conflict surface */}
      <ConflictCard />

      {/* Agent grid */}
      <div>
        <h2 className="mb-3 text-sm font-semibold">Agent Health Status</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {agents.map((agent) => (
            <AgentCard key={agent.agent} agent={agent} />
          ))}
        </div>
      </div>

      {/* Cross-Agent Intelligence — rule-based, instant, no LLM cost */}
      {fullCtx && (
        <CrossAgentIntelligence
          context={fullCtx}
          className="rounded-lg border border-border bg-card p-5"
        />
      )}

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
          {data?.generated_at
            ? `Last updated: ${new Date(data.generated_at).toLocaleString()} · Data synthesized from all executive agents`
            : "💡 This dashboard synthesizes data from all executive agents. Refresh to run a new analysis."}
        </p>
      </div>
    </main>
  );
}
