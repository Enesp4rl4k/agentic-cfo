"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo } from "react";
import {
  Zap, TrendingDown, Clock, AlertCircle, CheckCircle, Users,
  Filter, ArrowUp, ArrowDown, Minus,
} from "lucide-react";
import {
  LineChart, Line, ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, BarChart, Bar, Cell,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import { formatPercent, formatNumber, getSeverityColorClass } from "@/lib/dashboard-utils";

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
  breach_probability: number; // 0-1
  priority: "critical" | "high" | "medium" | "low";
  status: string;
}

interface COOResult {
  job_id: string;
  processes: ProcessBottleneck[] | null;
  sla: { tickets: SLATicket[]; breach_rate: number; trend: Array<{ date: string; breach_pct: number }> } | null;
  error: string | null;
}

// ── Placeholder Data ──────────────────────────────────────────────────────────

const SAMPLE_DATA = {
  processes: `process_name,cycle_time,throughput,wip,constraint_type,impact_score
Order Processing,5,20,45,resource,92
Payment Verification,3,30,25,policy,78
Inventory Check,2,40,15,material,65
Shipping Preparation,4,25,35,resource,88
Quality Inspection,3,15,20,resource,72`,

  sla: `ticket_id,title,assigned_to,created_date,due_date,priority,status
T001,Sistem Entegrasyonu,Ali,2024-06-20,2024-07-25,critical,in_progress
T002,Veri Aktarımı,Fatma,2024-06-18,2024-07-20,high,in_progress
T003,API Geliştirme,Mehmet,2024-06-22,2024-07-30,high,in_progress
T004,Raporlama,Ayşe,2024-06-15,2024-07-18,medium,in_progress
T005,Kullanıcı Arayüzü,Can,2024-06-25,2024-08-05,medium,in_progress`,
};

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

function getConstraintLabel(type: string): string {
  const labels: Record<string, string> = {
    resource: "İnsan Kaynakları",
    policy: "Politika",
    market: "Pazar",
    material: "Malzeme",
  };
  return labels[type] || type;
}

// ── 3D-like Bubble Chart for Bottlenecks ──────────────────────────────────────

interface BubbleChartProps {
  processes: ProcessBottleneck[];
}

function BottleneckBubbleChart({ processes }: BubbleChartProps) {
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
        Süreç Darboğazları (Verimlilik vs Döngü Zamanı)
      </h3>
      <ResponsiveContainer width="100%" height={350}>
        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis
            dataKey="cycle_time"
            name="Döngü Zamanı (gün)"
            stroke="currentColor"
            opacity={0.5}
          />
          <YAxis
            dataKey="throughput"
            name="Verimlilik (item/gün)"
            stroke="currentColor"
            opacity={0.5}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{ backgroundColor: "transparent", border: "none" }}
            formatter={(value) => fmt(value as number, 0)}
          />
          <Scatter
            name="Darboğazlar"
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
        {Object.entries({
          resource: "İnsan Kaynakları",
          policy: "Politika",
          market: "Pazar",
          material: "Malzeme",
        }).map(([type, label]) => (
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
  const topConstraints = useMemo(
    () => processes.sort((a, b) => b.impact_score - a.impact_score).slice(0, 5),
    [processes]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingDown className="h-4 w-4" />
        Kısıtlama Teorisi (ToC) Analizi
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
                {getConstraintLabel(proc.constraint_type)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Etki Puanı</span>
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

// ── SLA Trend Chart ───────────────────────────────────────────────────────────

interface SLATrendProps {
  trend: Array<{ date: string; breach_pct: number }>;
  breachRate: number;
}

function SLATrendChart({ trend, breachRate }: SLATrendProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingDown className="h-4 w-4" />
        SLA İhlali Trendi
      </h3>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Güncel İhlal Oranı</span>
        <span
          className={`text-lg font-bold ${breachRate > 0.1 ? "text-red-400" : "text-green-400"}`}
        >
          {formatPercent(breachRate)}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={trend}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis dataKey="date" stroke="currentColor" opacity={0.5} tick={{ fontSize: 12 }} />
          <YAxis stroke="currentColor" opacity={0.5} tick={{ fontSize: 12 }} />
          <Tooltip contentStyle={{ backgroundColor: "transparent", border: "none" }} />
          <Line
            type="monotone"
            dataKey="breach_pct"
            stroke="#ef4444"
            strokeWidth={2}
            name="İhlal %"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── At-Risk Tickets Table ─────────────────────────────────────────────────────

interface AtRiskTableProps {
  tickets: SLATicket[];
  onSort: (field: string) => void;
}

function AtRiskTicketsTable({ tickets, onSort }: AtRiskTableProps) {
  const atRiskTickets = useMemo(
    () =>
      tickets
        .filter((t) => t.breach_probability > 0.3)
        .sort((a, b) => b.breach_probability - a.breach_probability),
    [tickets]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <AlertCircle className="h-4 w-4" />
        Risk Altında Biletler ({atRiskTickets.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 px-2 font-semibold">Bilet</th>
              <th className="text-left py-2 px-2 font-semibold">Başlık</th>
              <th className="text-left py-2 px-2 font-semibold">Atanan</th>
              <th className="text-center py-2 px-2 font-semibold">Kalan Saat</th>
              <th className="text-center py-2 px-2 font-semibold">İhlal İht.</th>
              <th className="text-center py-2 px-2 font-semibold">Öncelik</th>
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
                      ticket.breach_probability > 0.7
                        ? "bg-red-500/20 text-red-400"
                        : "bg-yellow-500/20 text-yellow-400"
                    }`}
                  >
                    {formatPercent(ticket.breach_probability)}
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
  const [processCsv, setProcessCsv] = useState("");
  const [slaCsv, setSlaCsv] = useState("");
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<COOResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterPriority, setFilterPriority] = useState<string>("all");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!processCsv && !slaCsv) {
      setError("En az bir veri kaynağı (süreçler veya SLA CSV) gereklidir.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<COOResult>("/coo/analyze", {
        company_name: company || null,
        period: period || null,
        process_csv: processCsv || null,
        sla_csv: slaCsv || null,
      });
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
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
        hours_remaining: hoursRemaining,
        breach_probability: Math.max(0, Math.min(1, 1 - hoursRemaining / 168)), // 1 week baseline
        priority: (values[5]?.trim().toLowerCase() as any) || "medium",
        status: values[6]?.trim() || "",
      };
    });
  }, [slaCsv]);

  const mockTrend = [
    { date: "1 Haz", breach_pct: 15 },
    { date: "8 Haz", breach_pct: 12 },
    { date: "15 Haz", breach_pct: 18 },
    { date: "22 Haz", breach_pct: 14 },
    { date: "29 Haz", breach_pct: 11 },
  ];

  const breachRate = parsedTickets.length > 0
    ? parsedTickets.filter((t) => t.breach_probability > 0.5).length / parsedTickets.length
    : 0;

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Zap className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">COO Operasyon Panosu</h1>
          <p className="text-sm text-muted-foreground">
            Süreç darboğazları, ToC analizi ve SLA izleme
          </p>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4 sm:p-6">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="coo-company" className="mb-1 block text-xs font-medium">
              Şirket Adı
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
              Dönem
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

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="coo-processes" className="mb-1 block text-xs font-medium">
              Süreçler CSV
            </label>
            <textarea
              id="coo-processes"
              value={processCsv}
              onChange={(e) => setProcessCsv(e.target.value)}
              placeholder="CSV verisi yapıştırın..."
              rows={6}
              className="w-full rounded border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="coo-sla" className="mb-1 block text-xs font-medium">
              SLA / Biletler CSV
            </label>
            <textarea
              id="coo-sla"
              value={slaCsv}
              onChange={(e) => setSlaCsv(e.target.value)}
              placeholder="CSV verisi yapıştırın..."
              rows={6}
              className="w-full rounded border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
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
            {loading ? "Analiz yapılıyor…" : "COO Analizi Çalıştır"}
          </button>
          <button
            type="button"
            onClick={() => {
              setProcessCsv(SAMPLE_DATA.processes);
              setSlaCsv(SAMPLE_DATA.sla);
            }}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Örnek Veri Yükle
          </button>
        </div>
      </form>

      {/* Results */}
      {(parsedProcesses.length > 0 || parsedTickets.length > 0) && (
        <div className="space-y-6">
          {/* Row 1: Bottleneck bubble + ToC */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {parsedProcesses.length > 0 && <BottleneckBubbleChart processes={parsedProcesses} />}
            {parsedProcesses.length > 0 && <TOCAnalysis processes={parsedProcesses} />}
          </div>

          {/* Row 2: SLA Trend + At-Risk */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {parsedTickets.length > 0 && <SLATrendChart trend={mockTrend} breachRate={breachRate} />}
            {parsedTickets.length > 0 && (
              <AtRiskTicketsTable tickets={parsedTickets} onSort={() => {}} />
            )}
          </div>

          {result?.error && (
            <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
              Hata: {result.error}
            </div>
          )}
        </div>
      )}
    </main>
  );
}
