"use client";

/**
 * AgentPipelineGraph — CSS-based pipeline execution visualizer.
 *
 * Renders the Agentic CFO multi-domain pipeline as an interactive node graph.
 * No external graph library required — uses CSS Grid + SVG edges.
 *
 * Features:
 * - Static topology loaded from /api/v1/agent-graph/topology
 * - Live job status overlaid from /api/v1/agent-graph/job/{jobId}
 * - Auto-polls every 3s while a job is running
 * - Node click → detail popover (step name, status, confidence, duration)
 * - Group color coding: CFO (blue), Kernels (violet), Synthesis (emerald), Output (sky)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  group: string;
  color: string;
  x: number;   // grid column (0-based)
  y: number;   // grid row (0-based)
  // runtime
  status?: "pending" | "running" | "success" | "error";
  detail?: string | null;
  confidence?: number | null;
  duration_ms?: number | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  job_id?: string;
  job_status?: string;
  progress_pct?: number;
  running_node?: string | null;
}

// ── Color helpers ─────────────────────────────────────────────────────────────

function nodeColorClasses(color: string, status?: string): string {
  const statusOverride: Record<string, string> = {
    success: "border-emerald-500 bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
    error:   "border-red-500 bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200",
    running: "border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200 animate-pulse",
  };

  if (status && statusOverride[status]) return statusOverride[status];

  const colorMap: Record<string, string> = {
    blue:   "border-blue-400 bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
    violet: "border-violet-400 bg-violet-50 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
    amber:  "border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
    emerald:"border-emerald-400 bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
    sky:    "border-sky-400 bg-sky-50 text-sky-800 dark:bg-sky-950 dark:text-sky-200",
    rose:   "border-rose-400 bg-rose-50 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
    gray:   "border-border bg-muted text-muted-foreground",
  };

  return colorMap[color] ?? colorMap.gray;
}

function statusIcon(status?: string): string {
  switch (status) {
    case "success": return "✓";
    case "error":   return "✗";
    case "running": return "⟳";
    default:        return "○";
  }
}

// ── Node detail popover ───────────────────────────────────────────────────────

function NodePopover({
  node,
  onClose,
}: {
  node: GraphNode;
  onClose: () => void;
}) {
  return (
    <div
      className="absolute z-30 left-1/2 -translate-x-1/2 top-full mt-2 w-56 rounded-lg border border-border bg-card p-3 shadow-lg text-xs"
      role="tooltip"
    >
      <button
        onClick={onClose}
        className="absolute top-1.5 right-2 text-muted-foreground hover:text-foreground"
        aria-label="Close"
      >
        ×
      </button>
      <p className="font-semibold text-sm mb-1">{node.label}</p>
      <div className="space-y-0.5 text-muted-foreground">
        <p>Group: <span className="text-foreground">{node.group}</span></p>
        <p>Status: <span className={cn(
          "font-medium",
          node.status === "success" && "text-emerald-600",
          node.status === "error"   && "text-red-600",
          node.status === "running" && "text-amber-600",
        )}>{node.status ?? "pending"}</span></p>
        {node.confidence != null && (
          <p>Confidence: <span className="text-foreground">{(node.confidence * 100).toFixed(0)}%</span></p>
        )}
        {node.duration_ms != null && (
          <p>Duration: <span className="text-foreground">{node.duration_ms}ms</span></p>
        )}
        {node.detail && (
          <p className="mt-1 border-t border-border pt-1 text-foreground line-clamp-3">{node.detail}</p>
        )}
      </div>
    </div>
  );
}

// ── Graph node ────────────────────────────────────────────────────────────────

function PipelineNode({
  node,
  isSelected,
  onClick,
}: {
  node: GraphNode;
  isSelected: boolean;
  onClick: (node: GraphNode) => void;
}) {
  return (
    <div className="relative flex justify-center">
      <button
        onClick={() => onClick(node)}
        aria-label={`${node.label} — ${node.status ?? "pending"}`}
        className={cn(
          "relative flex items-center gap-1.5 rounded-md border-2 px-2.5 py-1.5",
          "text-xs font-medium transition-all duration-200",
          "hover:scale-105 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          nodeColorClasses(node.color, node.status),
          isSelected && "ring-2 ring-offset-1 ring-ring scale-105 shadow-md",
        )}
      >
        <span aria-hidden="true" className="shrink-0 font-mono text-[10px]">
          {statusIcon(node.status)}
        </span>
        <span className="whitespace-nowrap">{node.label}</span>
      </button>

      {isSelected && (
        <NodePopover
          node={node}
          onClose={() => onClick(node)}
        />
      )}
    </div>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────

const LEGEND_ITEMS = [
  { status: "pending", label: "Bekliyor",    cls: "bg-muted border-border" },
  { status: "running", label: "Çalışıyor",   cls: "bg-amber-100 border-amber-400 animate-pulse" },
  { status: "success", label: "Tamamlandı",  cls: "bg-emerald-100 border-emerald-500" },
  { status: "error",   label: "Hata",        cls: "bg-red-100 border-red-500" },
];

const GROUP_LEGEND = [
  { color: "bg-blue-400",   label: "CFO Pipeline" },
  { color: "bg-violet-400", label: "C-Suite Kernels" },
  { color: "bg-amber-400",  label: "Orchestrator" },
  { color: "bg-emerald-400",label: "CEO Sentezi" },
  { color: "bg-sky-400",    label: "Çıktılar" },
];

// ── Main component ────────────────────────────────────────────────────────────

interface AgentPipelineGraphProps {
  jobId?: string | null;
  /** Poll interval in ms while job is running (default 3000) */
  pollInterval?: number;
  className?: string;
  /** Show simplified legend */
  showLegend?: boolean;
}

export function AgentPipelineGraph({
  jobId,
  pollInterval = 3000,
  className,
  showLegend = true,
}: AgentPipelineGraphProps) {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const fetchGraph = useCallback(async () => {
    try {
      const url = jobId
        ? `${API_BASE}/api/v1/agent-graph/job/${jobId}`
        : `${API_BASE}/api/v1/agent-graph/topology`;

      const token = typeof window !== "undefined"
        ? localStorage.getItem("access_token") ?? ""
        : "";

      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setGraphData(json.data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Graph yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, [jobId, API_BASE]);

  // Initial load
  useEffect(() => {
    setLoading(true);
    fetchGraph();
  }, [fetchGraph]);

  // Poll while job is running
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);

    const isRunning = graphData?.job_status === "running" || graphData?.job_status === "pending";
    if (jobId && isRunning) {
      pollRef.current = setInterval(fetchGraph, pollInterval);
    }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [graphData?.job_status, jobId, fetchGraph, pollInterval]);

  function handleNodeClick(node: GraphNode) {
    setSelectedNode(prev => prev === node.id ? null : node.id);
  }

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center py-16 text-muted-foreground text-sm", className)}>
        <span className="animate-pulse">Pipeline yükleniyor…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={cn("rounded-lg border border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground", className)}>
        <p>Graph verisi alınamadı: {error}</p>
        <button onClick={fetchGraph} className="mt-2 text-primary underline">Yeniden dene</button>
      </div>
    );
  }

  if (!graphData) return null;

  const { nodes, progress_pct, job_status } = graphData;

  // Group nodes by x-column for layout
  const maxCol = Math.max(...nodes.map(n => n.x));
  const columns: GraphNode[][] = Array.from({ length: maxCol + 1 }, (_, col) =>
    nodes
      .filter(n => n.x === col)
      .sort((a, b) => a.y - b.y)
  );

  return (
    <div className={cn("space-y-4", className)}>
      {/* Progress bar */}
      {jobId && progress_pct != null && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Pipeline İlerlemesi</span>
            <span className={cn(
              "font-medium",
              job_status === "completed" && "text-emerald-600",
              job_status === "failed"    && "text-red-600",
            )}>
              {progress_pct}%
              {job_status && ` — ${job_status}`}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                job_status === "failed" ? "bg-red-500" : "bg-primary",
              )}
              style={{ width: `${progress_pct}%` }}
              role="progressbar"
              aria-valuenow={progress_pct}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>
      )}

      {/* Graph: columns of nodes */}
      <div
        className="overflow-x-auto rounded-lg border border-border bg-card p-4"
        role="img"
        aria-label="Agent pipeline graph"
      >
        <div
          className="flex gap-6 items-start min-w-max"
          style={{ minHeight: 320 }}
        >
          {columns.map((col, colIdx) => (
            <div key={colIdx} className="flex flex-col gap-3 min-w-[120px]">
              {col.map(node => (
                <PipelineNode
                  key={node.id}
                  node={node}
                  isSelected={selectedNode === node.id}
                  onClick={handleNodeClick}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      {showLegend && (
        <div className="flex flex-wrap gap-6 text-xs text-muted-foreground">
          <div className="flex flex-wrap gap-3">
            {LEGEND_ITEMS.map(item => (
              <div key={item.status} className="flex items-center gap-1.5">
                <span className={cn("inline-block h-3 w-3 rounded-sm border-2", item.cls)} />
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            {GROUP_LEGEND.map(item => (
              <div key={item.label} className="flex items-center gap-1.5">
                <span className={cn("inline-block h-2.5 w-2.5 rounded-full", item.color)} />
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default AgentPipelineGraph;
