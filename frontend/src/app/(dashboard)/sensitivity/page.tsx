"use client";

export const dynamic = "force-dynamic";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  FlaskConical, TrendingUp, TrendingDown, AlertTriangle,
  ChevronDown, RefreshCw,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { useActiveCFOJob } from "@/hooks/useCompanyContext";
import { useI18n } from "@/hooks/useI18n";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Variable {
  key: string;
  label: string;
  default_range: number[];
  unit: string;
}

interface MatrixResult {
  row_variable: string;
  col_variable: string;
  row_label: string;
  col_label: string;
  row_values: number[];
  col_values: number[];
  matrix: number[][];          // [row][col] = net_income cents
  matrix_margin: number[][];   // [row][col] = net_margin %
  base_net_income: number;
  best_case: { row_pct: number; col_pct: number; net_income: number; label: string };
  worst_case: { row_pct: number; col_pct: number; net_income: number; label: string };
}

interface SingleResult {
  variable: string;
  variable_label: string;
  base_net_income: number;
  outcomes: Array<{
    change_pct: number;
    net_income: number;
    net_margin_pct: number;
    delta_pct: number;
    label: string;
  }>;
  breakeven_threshold: number | null;
  min_outcome: number;
  max_outcome: number;
}

// ── API ───────────────────────────────────────────────────────────────────────

async function fetchVariables(jobId: string): Promise<Variable[]> {
  const res = await apiClient.get<{ data: { variables: Variable[] } }>(
    `/analysis/${jobId}/sensitivity/variables`
  );
  return res.data.data.variables;
}

async function fetchMatrix(jobId: string, rowVar: string, colVar: string): Promise<MatrixResult> {
  const res = await apiClient.post<{ data: MatrixResult }>(
    `/analysis/${jobId}/sensitivity/matrix`,
    { row_variable: rowVar, col_variable: colVar }
  );
  return res.data.data;
}

async function fetchSingle(jobId: string, variable: string): Promise<SingleResult> {
  const res = await apiClient.post<{ data: SingleResult }>(
    `/analysis/${jobId}/sensitivity/variable`,
    { variable }
  );
  return res.data.data;
}

// ── Heatmap cell color ────────────────────────────────────────────────────────

function cellColor(value: number, min: number, max: number, base: number): string {
  if (max === min) return "bg-muted/40";
  const normalized = (value - min) / (max - min); // 0..1

  if (value < 0) {
    // Negative: red scale
    const intensity = Math.min(1, Math.abs(value) / Math.max(Math.abs(min), 1));
    if (intensity > 0.7) return "bg-red-900/70 text-red-100";
    if (intensity > 0.4) return "bg-red-800/50 text-red-200";
    return "bg-red-700/30 text-red-300";
  }

  if (normalized > 0.8) return "bg-emerald-700/60 text-emerald-100";
  if (normalized > 0.6) return "bg-emerald-700/40 text-emerald-200";
  if (normalized > 0.4) return "bg-emerald-700/20 text-emerald-300";
  if (normalized > 0.2) return "bg-muted/40 text-foreground";
  return "bg-muted/20 text-muted-foreground";
}

// ── Heatmap component ─────────────────────────────────────────────────────────

function SensitivityHeatmap({ result }: { result: MatrixResult }) {
  const [showMargin, setShowMargin] = useState(false);
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { heatmap } = t.sensitivity;
  const allVals = result.matrix.flat();
  const minVal = Math.min(...allVals);
  const maxVal = Math.max(...allVals);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4 flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold">{heatmap.heading}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {heatmap.subtitle
              .replace("{row}", result.row_label)
              .replace("{col}", result.col_label)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowMargin((v) => !v)}
            className="rounded border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted transition-state"
          >
            {showMargin ? heatmap.showNet : heatmap.showMargin}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">
          <thead>
            <tr>
              {/* Top-left corner */}
              <th className="px-2 py-1.5 text-left text-muted-foreground font-normal border-b border-r border-border">
                <span className="text-[10px]">{result.row_label.slice(0, 12)}…</span>
                <br />
                <span className="text-[9px] opacity-60">↓ / {result.col_label.slice(0, 12)}… →</span>
              </th>
              {result.col_values.map((cv) => (
                <th
                  key={cv}
                  className="px-2 py-1.5 text-center font-semibold text-muted-foreground border-b border-border"
                >
                  {cv > 0 ? `+${cv}` : cv}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.row_values.map((rv, ri) => (
              <tr key={rv} className="hover:bg-muted/10 transition-state">
                {/* Row header */}
                <td className="px-2 py-1.5 text-center font-semibold text-muted-foreground border-r border-border whitespace-nowrap">
                  {rv > 0 ? `+${rv}` : rv}%
                </td>
                {result.col_values.map((_cv, ci) => {
                  const val = showMargin
                    ? result.matrix_margin[ri][ci]
                    : result.matrix[ri][ci];
                  const color = cellColor(
                    result.matrix[ri][ci],
                    minVal,
                    maxVal,
                    result.base_net_income
                  );
                  const isBase = rv === 0 && _cv === 0;

                  return (
                    <td
                      key={ci}
                      className={cn(
                        "px-2 py-1.5 text-center tabular-nums rounded-sm",
                        color,
                        isBase && "ring-1 ring-primary/60 font-bold"
                      )}
                      title={
                        showMargin
                          ? heatmap.marginTooltip.replace("{val}", val.toFixed(1))
                          : heatmap.netTooltip.replace("{val}", fmt(val))
                      }
                    >
                      {showMargin
                        ? `${val.toFixed(1)}%`
                        : val >= 0
                        ? `+${(val / 1_000_000).toFixed(1)}M`
                        : `${(val / 1_000_000).toFixed(1)}M`
                      }
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-emerald-700/60" /> {heatmap.legendHigh}</div>
        <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-muted/40" /> {heatmap.legendBase}</div>
        <div className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-red-700/60" /> {heatmap.legendLow}</div>
        {result.base_net_income !== 0 && (
          <span className="ml-auto">
            {heatmap.baseNet} <strong className="text-foreground">{fmt(result.base_net_income)}</strong>
          </span>
        )}
      </div>

      {/* Best / Worst case */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
            <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wide">{heatmap.bestCase}</span>
          </div>
          <p className="text-xs text-muted-foreground">{result.best_case.label}</p>
          <p className="text-sm font-bold text-emerald-400 mt-0.5">
            {fmt(result.best_case.net_income)}
          </p>
        </div>
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2.5">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingDown className="h-3.5 w-3.5 text-red-400" aria-hidden="true" />
            <span className="text-[10px] font-semibold text-red-400 uppercase tracking-wide">{heatmap.worstCase}</span>
          </div>
          <p className="text-xs text-muted-foreground">{result.worst_case.label}</p>
          <p className="text-sm font-bold text-red-400 mt-0.5">
            {fmt(result.worst_case.net_income)}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── 1D Chart component ────────────────────────────────────────────────────────

function SingleVariableChart({ result }: { result: SingleResult }) {
  const fmt = useCurrencyFormat();
  const { t } = useI18n();
  const { single } = t.sensitivity;

  const chartData = result.outcomes.map((o) => ({
    change: `${o.change_pct > 0 ? "+" : ""}${o.change_pct}%`,
    net_income: Math.round(o.net_income),
    margin: o.net_margin_pct,
    isBase: o.change_pct === 0,
  }));

  const hasBreakeven = result.breakeven_threshold !== null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-1 text-sm font-semibold">
        {single.heading.replace("{label}", result.variable_label)}
      </h3>
      <p className="mb-4 text-xs text-muted-foreground">
        {single.subtitle}
      </p>

      {hasBreakeven && (
        <div className="mb-3 flex items-center gap-2 rounded border border-warning/30 bg-warning/5 px-3 py-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-warning shrink-0" aria-hidden="true" />
          <p className="text-xs text-warning">
            {single.breakeven.replace("{threshold}", result.breakeven_threshold?.toFixed(1) ?? "")}
          </p>
        </div>
      )}

      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.07} />
          <XAxis
            dataKey="change"
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            opacity={0.4}
          />
          <YAxis
            tickFormatter={(v) => `${(v / 1_000_000).toFixed(1)}M`}
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            opacity={0.4}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              fontSize: 12,
            }}
            formatter={(value: number) => [fmt(value), single.tooltip]}
          />
          <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.3} />
          <Bar
            dataKey="net_income"
            radius={[3, 3, 0, 0]}
            fill="var(--primary)"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Variable selector ─────────────────────────────────────────────────────────

function VarSelect({
  id,
  label,
  value,
  onChange,
  variables,
  exclude,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  variables: Variable[];
  exclude?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(
            "w-full appearance-none rounded-md border border-input bg-background px-3 py-2 pr-8 text-sm",
            "focus:outline-none focus:ring-1 focus:ring-ring transition-state"
          )}
        >
          {variables.filter((v) => v.key !== exclude).map((v) => (
            <option key={v.key} value={v.key}>{v.label}</option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SensitivityPage() {
  const searchParams = useSearchParams();
  const urlJobId = searchParams.get("job");
  const contextJobId = useActiveCFOJob();
  const jobId = urlJobId ?? contextJobId;
  const { t } = useI18n();
  const s = t.sensitivity;

  const [rowVar, setRowVar] = useState("headcount_change_pct");
  const [colVar, setColVar] = useState("pricing_change_pct");
  const [singleVar, setSingleVar] = useState("headcount_change_pct");
  const [activeTab, setActiveTab] = useState<"matrix" | "single">("matrix");

  // Fetch available variables
  const { data: variables, isLoading: varsLoading } = useQuery({
    queryKey: ["sensitivity-variables", jobId],
    queryFn: () => fetchVariables(jobId!),
    enabled: !!jobId,
    staleTime: Infinity,
  });

  // Matrix mutation
  const matrixMutation = useMutation({
    mutationFn: () => fetchMatrix(jobId!, rowVar, colVar),
  });

  // Single variable mutation
  const singleMutation = useMutation({
    mutationFn: () => fetchSingle(jobId!, singleVar),
  });

  const handleRun = () => {
    if (activeTab === "matrix") matrixMutation.mutate();
    else singleMutation.mutate();
  };

  // No job
  if (!jobId) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-6 text-center">
        <FlaskConical className="mb-4 h-12 w-12 text-muted-foreground/30" aria-hidden="true" />
        <h2 className="text-base font-semibold">{s.noJob.heading}</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
          {s.noJob.body}
        </p>
        <a
          href="/upload"
          className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 transition-state"
        >
          {s.noJob.cta}
        </a>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-6 p-4 sm:p-6 lg:p-8 page-enter">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="rounded-lg bg-primary/10 p-2">
          <FlaskConical className="h-6 w-6 text-primary" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-xl font-bold">{s.title}</h1>
          <p className="text-sm text-muted-foreground">
            {s.subtitle}
          </p>
        </div>
      </div>

      {/* Config panel */}
      <div className="rounded-lg border border-border bg-card p-4 sm:p-6">
        {/* Tabs */}
        <div className="mb-5 flex gap-1 rounded-lg bg-muted/40 p-1 w-fit">
          {(["matrix", "single"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-medium transition-state",
                activeTab === tab
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {tab === "matrix" ? s.tabs.matrix : s.tabs.single}
            </button>
          ))}
        </div>

        {varsLoading ? (
          <div className="h-20 flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
            {s.varsLoading}
          </div>
        ) : variables && variables.length > 0 ? (
          <div className="space-y-4">
            {activeTab === "matrix" ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <VarSelect
                  id="row-var"
                  label={s.labels.rowVar}
                  value={rowVar}
                  onChange={setRowVar}
                  variables={variables}
                  exclude={colVar}
                />
                <VarSelect
                  id="col-var"
                  label={s.labels.colVar}
                  value={colVar}
                  onChange={setColVar}
                  variables={variables}
                  exclude={rowVar}
                />
              </div>
            ) : (
              <VarSelect
                id="single-var"
                label={s.labels.singleVar}
                value={singleVar}
                onChange={setSingleVar}
                variables={variables}
              />
            )}

            <div className="flex items-center gap-3">
              <button
                onClick={handleRun}
                disabled={matrixMutation.isPending || singleMutation.isPending}
                className={cn(
                  "flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground",
                  "hover:opacity-90 transition-state press-feedback disabled:opacity-50"
                )}
              >
                {(matrixMutation.isPending || singleMutation.isPending) ? (
                  <><RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />{s.calculating}</>
                ) : (
                  <><FlaskConical className="h-4 w-4" aria-hidden="true" />{s.run}</>
                )}
              </button>

              {(matrixMutation.isError || singleMutation.isError) && (
                <p className="text-xs text-destructive">
                  {s.error}
                </p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {s.needAnalysis}
          </p>
        )}
      </div>

      {/* Results */}
      {matrixMutation.data && activeTab === "matrix" && (
        <SensitivityHeatmap result={matrixMutation.data} />
      )}
      {singleMutation.data && activeTab === "single" && (
        <SingleVariableChart result={singleMutation.data} />
      )}

      {/* Info box */}
      {!matrixMutation.data && !singleMutation.data && (
        <div className="rounded-lg border border-dashed border-border bg-muted/10 p-6 text-center">
          <p className="text-sm text-muted-foreground">
            {s.info.body.replace("{run}", s.run)}
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-3 text-xs text-muted-foreground/70">
            <span>• {s.info.ex1}</span>
            <span>• {s.info.ex2}</span>
            <span>• {s.info.ex3}</span>
          </div>
        </div>
      )}
    </main>
  );
}
