"use client";

export const dynamic = "force-dynamic";

import { useState, useMemo } from "react";
import {
  FileSearch, AlertTriangle, CheckCircle, Shield, BarChart2, Clock,
  TrendingUp, Calendar, Users, Target, ChevronDown, X, Info,
} from "lucide-react";
import {
  LineChart, Line, BarChart, Bar, ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell,
} from "recharts";
import { apiClient } from "@/lib/api/client";
import {
  formatDateTR, formatPercent, getSeverityColorClass, daysBetween,
  generateHeatmapData, valueToColor,
} from "@/lib/dashboard-utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Finding {
  finding_id: string;
  title: string;
  severity: string;
  status: string;
  due_date: string;
  owner: string;
  category: string;
  remediation_status: string;
  days_overdue?: number;
}

interface Control {
  control_id: string;
  name: string;
  category: string;
  design_effectiveness: number;
  operating_effectiveness: number;
  combined_score: number;
  last_tested: string;
  owner: string;
  status: string;
}

interface AuditSummary {
  overall_audit_score: number;
  audit_maturity: string;
  component_scores: Record<string, number>;
  top_risks: Array<{ domain: string; severity: string; message: string }>;
  quick_wins: Array<{ action: string; estimated_impact: string; effort: string }>;
  narrative: string;
}

interface AuditResult {
  job_id: string;
  findings: any | null;
  controls: any | null;
  coverage: any | null;
  audit_summary: AuditSummary | null;
  error: string | null;
}

// ── Placeholder CSV data ──────────────────────────────────────────────────────

const SAMPLE_DATA = {
  findings: `finding_id,title,severity,status,due_date,owner,category,remediation_status
F001,Şifrelenmemiş veri tabanı yedeklemesi,critical,open,2024-02-15,IT Security,data_security,in_progress
F002,Finansmanda görev ayrımı ihlali,high,open,2024-03-01,Finance,access_control,not_started
F003,Eksik felaket kurtarma planı,high,closed,2024-01-20,Operations,business_continuity,completed
F004,Zayıf şifre politikası uygulaması,medium,open,2024-03-10,IT,identity_management,in_progress
F005,Satıcı sözleşme inceleme süreci,medium,open,2024-02-28,Procurement,third_party_risk,not_started`,

  controls: `control_id,name,category,design_effectiveness,operating_effectiveness,last_tested,owner
C001,Güvenlik duvarı kuralı incelemesi,it_security,85,80,2024-01-15,CTO
C002,Görev ayrımı matrisi,access_control,90,75,2023-11-20,CFO
C003,Veri yedekleme doğrulaması,data_security,95,90,2024-02-01,IT Manager
C004,Satıcı risk değerlendirmesi,third_party,80,65,2023-10-05,Procurement
C005,Değişim yönetimi onayı,it_operations,85,85,2024-01-25,CTO`,

  coverage: `unit_name,category,last_audit,frequency,risk_rating,scheduled_next
IT Altyapısı,technology,2023-06-15,annual,high,2024-06-15
Ödenecek Hesaplar,finance,2023-09-01,annual,medium,2024-09-01
İK Bordrosu,hr,2024-01-10,annual,medium,2025-01-10
Üçüncü Taraf Satıcılar,procurement,2023-03-20,annual,high,2024-03-20
Fiziksel Güvenlik,operations,2023-08-15,annual,low,2024-08-15`,
};

// ── Helper functions ──────────────────────────────────────────────────────────

function fmt(n: unknown, decimals = 1): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return isNaN(v) ? "—" : v.toFixed(decimals);
}

function scoreColor(score: number): string {
  if (score >= 85) return "text-emerald-400";
  if (score >= 70) return "text-yellow-400";
  return "text-red-400";
}

// ── Control Effectiveness Heatmap ─────────────────────────────────────────────

interface HeatmapProps {
  controls: Control[];
}

function ControlHeatmap({ controls }: HeatmapProps) {
  const categories = Array.from(new Set(controls.map((c) => c.category)));
  const controlTypes = ["Design", "Operating"];

  const cells = useMemo(() => {
    const data: Array<{ x: number; y: number; category: string; type: string; value: number }> = [];
    categories.forEach((cat, i) => {
      controlTypes.forEach((type, j) => {
        const catControls = controls.filter((c) => c.category === cat);
        const avg =
          type === "Design"
            ? catControls.reduce((sum, c) => sum + c.design_effectiveness, 0) /
              catControls.length
            : catControls.reduce((sum, c) => sum + c.operating_effectiveness, 0) /
              catControls.length;
        data.push({
          x: j,
          y: i,
          category: cat,
          type,
          value: isNaN(avg) ? 0 : avg / 100,
        });
      });
    });
    return data;
  }, [controls, categories]);

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <Shield className="h-4 w-4" />
        Kontrol Etkinliği Heatmap (IIA Maturity)
      </h3>
      <div className="overflow-x-auto">
        <div className="min-w-[300px] grid gap-1 p-2" style={{ gridTemplateColumns: `60px repeat(${controlTypes.length}, 1fr)` }}>
          <div className="text-xs font-medium text-muted-foreground" />
          {controlTypes.map((type) => (
            <div key={type} className="text-xs font-medium text-center">{type}</div>
          ))}
          {categories.map((cat) => (
            <>
              <div key={`label-${cat}`} className="text-xs font-medium text-muted-foreground truncate">{cat.slice(0, 8)}</div>
              {controlTypes.map((type) => {
                const cell = cells.find((c) => c.category === cat && c.type === type);
                const color = valueToColor(cell?.value ?? 0);
                return (
                  <div
                    key={`${cat}-${type}`}
                    className="rounded p-2 text-center text-xs font-semibold text-white"
                    style={{ backgroundColor: color }}
                    title={`${cat} - ${type}: ${fmt((cell?.value ?? 0) * 100, 0)}%`}
                  >
                    {fmt((cell?.value ?? 0) * 100, 0)}%
                  </div>
                );
              })}
            </>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Repeat Findings Trend Chart ───────────────────────────────────────────────

function RepeatFindingsTrend() {
  const data = [
    { month: "Jan", repeat: 8, new: 12 },
    { month: "Feb", repeat: 5, new: 10 },
    { month: "Mar", repeat: 7, new: 9 },
    { month: "Apr", repeat: 4, new: 11 },
    { month: "May", repeat: 3, new: 8 },
    { month: "Jun", repeat: 2, new: 6 },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <TrendingUp className="h-4 w-4" />
        Tekrarlayan Bulgular Trendi
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.1} />
          <XAxis dataKey="month" stroke="currentColor" opacity={0.5} />
          <YAxis stroke="currentColor" opacity={0.5} />
          <Tooltip contentStyle={{ backgroundColor: "transparent", border: "none" }} />
          <Legend />
          <Line type="monotone" dataKey="repeat" stroke="#ef4444" strokeWidth={2} name="Tekrarlayan" />
          <Line type="monotone" dataKey="new" stroke="#3b82f6" strokeWidth={2} name="Yeni" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Risk-Based Audit Plan (Gantt-style) ───────────────────────────────────────

function AuditPlanGantt() {
  const tasks: Array<{ id: number; name: string; start: number; duration: number; risk: "high" | "medium" | "low" }> = [
    { id: 1, name: "IT Altyapısı", start: 0, duration: 15, risk: "high" },
    { id: 2, name: "Finansal Kontroller", start: 16, duration: 20, risk: "medium" },
    { id: 3, name: "İK Operasyonları", start: 37, duration: 18, risk: "low" },
    { id: 4, name: "Satıcı Yönetimi", start: 10, duration: 25, risk: "high" },
    { id: 5, name: "Bilgi Güvenliği", start: 28, duration: 22, risk: "high" },
  ];

  const riskColors: Record<"high" | "medium" | "low", string> = {
    high: "#ef4444",
    medium: "#f97316",
    low: "#10b981",
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
        <Calendar className="h-4 w-4" />
        90 Günlük Denetim Planı
      </h3>
      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium">{task.name}</span>
              <span
                className="text-xs px-2 py-0.5 rounded font-medium text-white"
                style={{ backgroundColor: riskColors[task.risk] }}
              >
                {task.risk.toUpperCase()}
              </span>
            </div>
            <div className="w-full bg-muted rounded h-6 relative overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${(task.duration / 90) * 100}%`,
                  left: `${(task.start / 90) * 100}%`,
                  backgroundColor: riskColors[task.risk],
                  opacity: 0.7,
                  position: "absolute",
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 text-xs text-muted-foreground">Toplam: 90 gün | Paralel: 5 denetim | Kapsamlılık: 98%</div>
    </div>
  );
}

// ── Finding Details Modal ─────────────────────────────────────────────────────

interface FindingModalProps {
  finding: Finding | null;
  onClose: () => void;
}

function FindingModal({ finding, onClose }: FindingModalProps) {
  if (!finding) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-full max-w-lg rounded-lg bg-card border border-border p-6 mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-lg font-bold">{finding.title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-muted-foreground">Önem Derecesi</p>
              <p className={`text-sm font-semibold ${scoreColor(finding.severity === "critical" ? 100 : 50)}`}>
                {finding.severity.toUpperCase()}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Durum</p>
              <p className="text-sm font-semibold">{finding.status.toUpperCase()}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Kategori</p>
              <p className="text-sm">{finding.category.replace(/_/g, " ")}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Sahip</p>
              <p className="text-sm">{finding.owner}</p>
            </div>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">Bitiş Tarihi</p>
            <p className="text-sm font-mono">{formatDateTR(finding.due_date)}</p>
            {finding.days_overdue && finding.days_overdue > 0 && (
              <p className="text-xs text-red-400 mt-1">⚠️ {finding.days_overdue} gün gecikmiş</p>
            )}
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">Düzeltme Durumu</p>
            <p className="text-sm capitalize">{finding.remediation_status.replace(/_/g, " ")}</p>
          </div>
        </div>

        <button
          onClick={onClose}
          className="mt-6 w-full rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          Kapat
        </button>
      </div>
    </div>
  );
}

// ── Main Page (Part 1) ───────────────────────────────────────────────────────

export default function AuditDashboardEnhancedPage() {
  const [findingsCsv, setFindingsCsv] = useState("");
  const [controlsCsv, setControlsCsv] = useState("");
  const [coverageCsv, setCoverageCsv] = useState("");
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AuditResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [sortBy, setSortBy] = useState<"severity" | "due_date" | "days_overdue">("severity");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!findingsCsv && !controlsCsv && !coverageCsv) {
      setError("En az bir veri kaynağı (bulgular, kontroller veya kapsam CSV) gereklidir.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<AuditResult>("/audit/analyze", {
        company_name: company || null,
        audit_period: period || null,
        findings_csv: findingsCsv || "",
        controls_csv: controlsCsv || "",
        coverage_csv: coverageCsv || "",
      });
      if (res.data.error) throw new Error(res.data.error);
      setResult(res.data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }

  const topFindings = useMemo(() => {
    if (!result?.findings?.top_overdue) return [];
    const findings = [...result.findings.top_overdue];
    if (sortBy === "severity") {
      const severityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
      findings.sort(
        (a, b) => (severityOrder[a.severity as keyof typeof severityOrder] ?? 99) -
          (severityOrder[b.severity as keyof typeof severityOrder] ?? 99)
      );
    } else if (sortBy === "due_date") {
      findings.sort((a, b) => new Date(a.due_date).getTime() - new Date(b.due_date).getTime());
    }
    return findings;
  }, [result, sortBy]);

  return (
    <main className="mx-auto max-w-screen-2xl space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <FileSearch className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">İç Denetim Panosu</h1>
          <p className="text-sm text-muted-foreground">
            Bulgular takibi, kontrol etkinliği ve denetim kapsama analizi
          </p>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4 sm:p-6">
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="audit-company" className="mb-1 block text-xs font-medium">Şirket Adı</label>
            <input
              id="audit-company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="Acme Corp"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div>
            <label htmlFor="audit-period" className="mb-1 block text-xs font-medium">Denetim Dönemi</label>
            <input
              id="audit-period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2024-Q2"
              className="w-full rounded border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {[
            { label: "Bulgular CSV", value: findingsCsv, set: setFindingsCsv, id: "audit-findings" },
            { label: "Kontroller CSV", value: controlsCsv, set: setControlsCsv, id: "audit-controls" },
            { label: "Kapsam CSV", value: coverageCsv, set: setCoverageCsv, id: "audit-coverage" },
          ].map(({ label, value, set, id }) => (
            <div key={id}>
              <label htmlFor={id} className="mb-1 block text-xs font-medium">{label}</label>
              <textarea
                id={id}
                value={value}
                onChange={(e) => set(e.target.value)}
                placeholder="CSV verisi yapıştırın..."
                rows={6}
                className="w-full rounded border border-input bg-background px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          ))}
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
            {loading ? "Analiz yapılıyor…" : "Denetimi Çalıştır"}
          </button>
          <button
            type="button"
            onClick={() => {
              setFindingsCsv(SAMPLE_DATA.findings);
              setControlsCsv(SAMPLE_DATA.controls);
              setCoverageCsv(SAMPLE_DATA.coverage);
            }}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Örnek Veri Yükle
          </button>
        </div>
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Top row: Heatmap + Gantt */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {result.controls && <ControlHeatmap controls={result.controls.weak_controls || []} />}
            <AuditPlanGantt />
          </div>

          {/* Second row: Trends + Summary */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <RepeatFindingsTrend />
            {result.audit_summary && (
              <div className="rounded-lg border border-border bg-card p-4">
                <h3 className="mb-4 text-sm font-semibold flex items-center gap-2">
                  <BarChart2 className="h-4 w-4" />
                  Denetim Özeti
                </h3>
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">Genel Puan</span>
                    <span className={`text-lg font-bold ${scoreColor(result.audit_summary.overall_audit_score * 10)}`}>
                      {fmt(result.audit_summary.overall_audit_score)}/10
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">Olgunluk</span>
                    <span className="text-sm font-semibold capitalize">{result.audit_summary.audit_maturity.replace(/_/g, " ")}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Top Findings with drill-down */}
          {result.findings && (
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-sm font-semibold flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" />
                  En Önemli Bulgular ({topFindings.length})
                </h3>
                <div className="flex items-center gap-2">
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as any)}
                    className="rounded border border-input bg-background px-2 py-1 text-xs"
                  >
                    <option value="severity">Önem Derecesi</option>
                    <option value="due_date">Bitiş Tarihi</option>
                    <option value="days_overdue">Gecikme</option>
                  </select>
                </div>
              </div>

              <div className="space-y-2">
                {topFindings.slice(0, 5).map((f) => (
                  <button
                    key={f.finding_id}
                    onClick={() => setSelectedFinding(f)}
                    className="w-full text-left rounded border border-border bg-muted/30 p-3 hover:bg-muted/50 transition"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm">{f.title}</p>
                        <div className="mt-1 flex flex-wrap gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded border ${getSeverityColorClass(f.severity)}`}>
                            {f.severity.toUpperCase()}
                          </span>
                          <span className="text-xs text-muted-foreground">{f.owner}</span>
                          <span className="text-xs text-muted-foreground">{formatDateTR(f.due_date)}</span>
                        </div>
                      </div>
                      <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-1" />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {result.error && (
            <div role="alert" className="rounded border border-red-400/30 bg-red-400/10 p-3 text-xs text-red-400">
              Pipeline hatası: {result.error}
            </div>
          )}
        </div>
      )}

      {/* Finding Detail Modal */}
      <FindingModal finding={selectedFinding} onClose={() => setSelectedFinding(null)} />
    </main>
  );
}
