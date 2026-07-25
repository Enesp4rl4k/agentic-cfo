"use client";

import { useState, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  Upload,
  ChevronDown,
  ChevronUp,
  Info,
  ShieldCheck,
  Eye,
  EyeOff,
} from "lucide-react";
import {
  useAnomalies,
  useScanAnomalies,
  useAcknowledgeAnomaly,
} from "@/hooks/useCFO";
import { cn } from "@/lib/utils";
import type { AnomalyItem } from "@/lib/api/cfo";

// ── Severity config ───────────────────────────────────────────────────────────

const SEVERITY_ORDER = ["critical", "high", "medium", "low"] as const;
type Severity = (typeof SEVERITY_ORDER)[number];

const SEVERITY_CONFIG: Record<
  Severity,
  {
    label: string;
    icon: React.ElementType;
    card: string;
    badge: string;
    pill: string;
    pillActive: string;
    dot: string;
    bar: string;
  }
> = {
  critical: {
    label: "Critical",
    icon: AlertCircle,
    card: "border-destructive/40 bg-destructive/5",
    badge: "bg-destructive/15 text-destructive ring-destructive/30",
    pill: "border-border text-muted-foreground hover:border-destructive/50 hover:text-destructive",
    pillActive: "border-destructive/50 bg-destructive/10 text-destructive",
    dot: "bg-destructive",
    bar: "bg-destructive",
  },
  high: {
    label: "High",
    icon: AlertTriangle,
    card: "border-orange-500/30 bg-orange-950/10",
    badge: "bg-orange-950/30 text-orange-400 ring-orange-500/25",
    pill: "border-border text-muted-foreground hover:border-orange-500/50 hover:text-orange-400",
    pillActive: "border-orange-500/50 bg-orange-950/20 text-orange-400",
    dot: "bg-orange-400",
    bar: "bg-orange-400",
  },
  medium: {
    label: "Medium",
    icon: AlertTriangle,
    card: "border-yellow-600/25 bg-yellow-950/10",
    badge: "bg-yellow-950/30 text-yellow-400 ring-yellow-600/25",
    pill: "border-border text-muted-foreground hover:border-yellow-600/50 hover:text-yellow-400",
    pillActive: "border-yellow-600/50 bg-yellow-950/20 text-yellow-400",
    dot: "bg-yellow-400",
    bar: "bg-yellow-400",
  },
  low: {
    label: "Low",
    icon: Info,
    card: "border-border bg-card",
    badge: "bg-muted text-muted-foreground ring-border",
    pill: "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
    pillActive: "border-primary/40 bg-primary/5 text-foreground",
    dot: "bg-muted-foreground",
    bar: "bg-muted-foreground",
  },
};

const ANOMALY_TYPE_LABELS: Record<string, string> = {
  duplicate_payment: "Duplicate Payment",
  unusual_amount: "Unusual Amount",
  unusual_vendor: "Unusual Vendor",
  vendor_concentration: "Vendor Concentration",
  negative_cashflow_streak: "Negative Cash Flow Streak",
  expense_spike: "Expense Spike",
  missing_revenue: "Missing Revenue",
  round_number: "Round Number Pattern",
  late_payment: "Late Payment",
  fx_concentration: "FX Concentration",
};

// ── Summary strip ─────────────────────────────────────────────────────────────

function SummaryStrip({
  total,
  bySeverity,
  activeSeverity,
  onFilter,
}: {
  total: number;
  bySeverity: Record<string, number>;
  activeSeverity: string;
  onFilter: (s: string) => void;
}) {
  const items = [
    { key: "all", label: "Total", value: total, cls: "text-foreground", activeCls: "ring-primary/40" },
    { key: "critical", label: "Critical", value: bySeverity.critical ?? 0, cls: "text-destructive", activeCls: "ring-destructive/40" },
    { key: "high", label: "High", value: bySeverity.high ?? 0, cls: "text-orange-400", activeCls: "ring-orange-400/40" },
    { key: "medium", label: "Medium", value: bySeverity.medium ?? 0, cls: "text-yellow-400", activeCls: "ring-yellow-400/40" },
    { key: "low", label: "Low", value: bySeverity.low ?? 0, cls: "text-muted-foreground", activeCls: "ring-muted-foreground/30" },
  ];

  return (
    <div className="grid grid-cols-5 gap-px overflow-hidden rounded-lg border border-border bg-border">
      {items.map((item) => {
        const isActive = activeSeverity === item.key;
        return (
          <button
            key={item.key}
            onClick={() => onFilter(item.key)}
            className={cn(
              "bg-card px-4 py-4 text-center transition-all",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
              isActive && `ring-2 ring-inset ${item.activeCls}`,
              !isActive && "hover:bg-muted/40"
            )}
            aria-pressed={isActive}
            aria-label={`Filter by ${item.label}`}
          >
            <p className="text-xs text-muted-foreground">{item.label}</p>
            <p className={cn("mt-1 text-xl font-semibold tabular-nums", item.cls)}>
              {item.value}
            </p>
          </button>
        );
      })}
    </div>
  );
}

// ── Confidence bar ────────────────────────────────────────────────────────────

function ConfidenceBar({ value, barClass }: { value: number; barClass: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2" aria-label={`Confidence: ${pct}%`}>
      <div className="h-1 w-16 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", barClass)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
    </div>
  );
}

// ── Anomaly card ──────────────────────────────────────────────────────────────

function AnomalyCard({
  anomaly,
  jobId,
}: {
  anomaly: AnomalyItem;
  jobId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const acknowledge = useAcknowledgeAnomaly(jobId);
  const sev = (anomaly.severity as Severity) in SEVERITY_CONFIG
    ? (anomaly.severity as Severity)
    : "low";
  const cfg = SEVERITY_CONFIG[sev];
  const Icon = cfg.icon;

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 transition-all duration-200",
        anomaly.acknowledged
          ? "border-border bg-card/40 opacity-55"
          : cfg.card
      )}
    >
      <div className="flex items-start gap-3">
        {/* Severity dot + icon */}
        <div className="mt-0.5 flex shrink-0 flex-col items-center gap-1">
          <Icon
            className={cn(
              "h-4 w-4",
              anomaly.acknowledged ? "text-muted-foreground" : `text-${sev === "critical" ? "destructive" : sev === "high" ? "orange-400" : sev === "medium" ? "yellow-400" : "muted-foreground"}`
            )}
            aria-hidden="true"
          />
        </div>

        <div className="flex-1 min-w-0">
          {/* Badge row */}
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
                anomaly.acknowledged ? "bg-muted text-muted-foreground ring-border" : cfg.badge
              )}
            >
              {cfg.label}
            </span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {ANOMALY_TYPE_LABELS[anomaly.anomaly_type] ?? anomaly.anomaly_type.replace(/_/g, " ")}
            </span>
            {anomaly.acknowledged && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <CheckCircle className="h-3 w-3" aria-hidden="true" />
                Acknowledged
              </span>
            )}
          </div>

          {/* Title + description */}
          <p className="mt-1.5 text-sm font-medium leading-snug">{anomaly.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            {anomaly.description}
          </p>

          {/* Confidence */}
          {anomaly.confidence != null && (
            <div className="mt-2">
              <ConfidenceBar value={anomaly.confidence} barClass={cfg.bar} />
            </div>
          )}

          {/* Evidence toggle */}
          {anomaly.evidence && Object.keys(anomaly.evidence).length > 0 && (
            <>
              <button
                onClick={() => setExpanded((v) => !v)}
                className="mt-2 flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                aria-expanded={expanded}
              >
                {expanded ? (
                  <ChevronUp className="h-3 w-3" aria-hidden="true" />
                ) : (
                  <ChevronDown className="h-3 w-3" aria-hidden="true" />
                )}
                {expanded ? "Hide evidence" : "Show evidence"}
              </button>

              {expanded && (
                <dl className="mt-2 rounded-md bg-muted/30 p-2.5 font-mono text-xs">
                  {Object.entries(anomaly.evidence).map(([k, v]) => (
                    <div key={k} className="flex gap-2 py-0.5">
                      <dt className="shrink-0 text-muted-foreground">{k}:</dt>
                      <dd className="break-all">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          )}
        </div>

        {/* Acknowledge button */}
        <button
          onClick={() =>
            acknowledge.mutate({ id: anomaly.id, ack: !anomaly.acknowledged })
          }
          disabled={acknowledge.isPending}
          className={cn(
            "shrink-0 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "disabled:pointer-events-none disabled:opacity-50",
            anomaly.acknowledged
              ? "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
              : "border-border bg-background/50 text-muted-foreground hover:border-emerald-500/40 hover:text-emerald-400"
          )}
          aria-label={anomaly.acknowledged ? "Restore anomaly" : "Acknowledge anomaly"}
        >
          {acknowledge.isPending ? (
            <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
          ) : anomaly.acknowledged ? (
            "Restore"
          ) : (
            "Dismiss"
          )}
        </button>
      </div>
    </div>
  );
}

// ── Section group ─────────────────────────────────────────────────────────────

function SeverityGroup({
  severity,
  anomalies,
  jobId,
}: {
  severity: Severity;
  anomalies: AnomalyItem[];
  jobId: string;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const cfg = SEVERITY_CONFIG[severity];
  const Icon = cfg.icon;

  if (!anomalies.length) return null;

  return (
    <section aria-label={`${cfg.label} anomalies`}>
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="mb-2 flex w-full items-center gap-2 text-left"
        aria-expanded={!collapsed}
      >
        <span
          className={cn("h-2 w-2 rounded-full shrink-0", cfg.dot)}
          aria-hidden="true"
        />
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {cfg.label}
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
            cfg.badge
          )}
        >
          {anomalies.length}
        </span>
        <span className="ml-auto">
          {collapsed ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          )}
        </span>
      </button>

      {!collapsed && (
        <div className="space-y-2">
          {anomalies.map((a) => (
            <AnomalyCard key={a.id} anomaly={a} jobId={jobId} />
          ))}
        </div>
      )}
    </section>
  );
}

// ── Empty / clean states ──────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">No anomaly data</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Complete an analysis first, then scan for anomalies.
      </p>
      <a
        href="/upload"
        className={cn(
          "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Upload document
      </a>
    </div>
  );
}

function CleanState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-emerald-950/30 p-4">
        <ShieldCheck className="h-8 w-8 text-emerald-400" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold text-emerald-400">All clear</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        No anomalies detected in your financial data.
      </p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AnomaliesPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const [filterSeverity, setFilterSeverity] = useState<string>("all");
  const [filterType, setFilterType] = useState<string>("all");
  const [showAcknowledged, setShowAcknowledged] = useState(false);

  const { data, isLoading } = useAnomalies(jobId);
  const scan = useScanAnomalies(jobId);

  if (!jobId || (!isLoading && !data)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-3 p-5">
        <div className="h-6 w-48 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-5 gap-px overflow-hidden rounded-lg border border-border bg-border">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-card px-4 py-4">
              <div className="mx-auto h-3 w-12 animate-pulse rounded bg-muted" />
              <div className="mx-auto mt-2 h-6 w-8 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  const allAnomalies = data!.anomalies;

  // Counts per severity (from all, ignoring ack filter)
  const bySeverity = useMemo(() => {
    const counts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    allAnomalies.forEach((a) => {
      if (a.severity in counts) counts[a.severity]++;
    });
    return counts;
  }, [allAnomalies]);

  // Unique anomaly types for type filter
  const anomalyTypes = useMemo(() => {
    const types = new Set(allAnomalies.map((a) => a.anomaly_type));
    return Array.from(types).sort();
  }, [allAnomalies]);

  // Apply filters
  const filtered = useMemo(() => {
    return allAnomalies.filter((a) => {
      if (!showAcknowledged && a.acknowledged) return false;
      if (filterSeverity !== "all" && a.severity !== filterSeverity) return false;
      if (filterType !== "all" && a.anomaly_type !== filterType) return false;
      return true;
    });
  }, [allAnomalies, showAcknowledged, filterSeverity, filterType]);

  // Group by severity for display
  const grouped = useMemo(() => {
    const groups: Record<Severity, AnomalyItem[]> = {
      critical: [],
      high: [],
      medium: [],
      low: [],
    };
    filtered.forEach((a) => {
      const sev = a.severity as Severity;
      if (sev in groups) groups[sev].push(a);
      else groups.low.push(a);
    });
    return groups;
  }, [filtered]);

  const acknowledgedCount = allAnomalies.filter((a) => a.acknowledged).length;
  const hasFilters = filterSeverity !== "all" || filterType !== "all";

  return (
    <div className="space-y-4 p-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Anomaly Detection</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            AI-powered financial anomaly scanner
            {data!.total > 0 && (
              <>
                {" · "}
                <span className="text-foreground">{data!.total}</span> issues found
                {acknowledgedCount > 0 && (
                  <span className="ml-1 text-muted-foreground">
                    ({acknowledgedCount} dismissed)
                  </span>
                )}
              </>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Show/hide acknowledged */}
          <button
            onClick={() => setShowAcknowledged((v) => !v)}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              showAcknowledged
                ? "border-primary/40 bg-primary/5 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            )}
            aria-label={showAcknowledged ? "Hide acknowledged" : "Show acknowledged"}
          >
            {showAcknowledged ? (
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Dismissed {acknowledgedCount > 0 && `(${acknowledgedCount})`}
          </button>

          {/* Re-scan */}
          <button
            onClick={() => scan.mutate()}
            disabled={scan.isPending}
            className={cn(
              "flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-medium",
              "text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:pointer-events-none disabled:opacity-50"
            )}
            aria-label="Re-scan for anomalies"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", scan.isPending && "animate-spin")}
              aria-hidden="true"
            />
            {scan.isPending ? "Scanning…" : "Re-scan"}
          </button>
        </div>
      </div>

      {/* Summary strip — clickable to filter */}
      <SummaryStrip
        total={data!.total}
        bySeverity={bySeverity}
        activeSeverity={filterSeverity}
        onFilter={(s) => setFilterSeverity((prev) => (prev === s ? "all" : s))}
      />

      {/* Type filter + clear */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Filter by anomaly type"
        >
          <option value="all">All types</option>
          {anomalyTypes.map((t) => (
            <option key={t} value={t}>
              {ANOMALY_TYPE_LABELS[t] ?? t.replace(/_/g, " ")}
            </option>
          ))}
        </select>

        {hasFilters && (
          <button
            onClick={() => { setFilterSeverity("all"); setFilterType("all"); }}
            className="h-8 rounded-md border border-border px-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Clear filters
          </button>
        )}

        <span className="text-xs text-muted-foreground">
          {filtered.length} shown
        </span>
      </div>

      {/* Content */}
      {filtered.length === 0 ? (
        data!.total === 0 ? (
          <CleanState />
        ) : (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No anomalies match the current filters.
          </div>
        )
      ) : (
        <div className="space-y-6">
          {SEVERITY_ORDER.map((sev) => (
            <SeverityGroup
              key={sev}
              severity={sev}
              anomalies={grouped[sev]}
              jobId={jobId!}
            />
          ))}
        </div>
      )}
    </div>
  );
}
