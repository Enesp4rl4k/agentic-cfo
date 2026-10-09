"use client";

export const dynamic = "force-dynamic";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  DollarSign, TrendingUp, TrendingDown, AlertTriangle,
  FileText, Download, Upload, ChevronRight, BarChart2,
  Waves, Activity, ShieldAlert,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { useDashboard, useTopAlerts, useReports } from "@/hooks/useCFO";
import { useActiveCFOJob } from "@/hooks/useCompanyContext";
import { formatPercent, cn } from "@/lib/utils";
import { useCurrencyFormat, useCurrencySymbol } from "@/hooks/useCurrencyFormat";
import { downloadReport } from "@/lib/api/cfo";
import type { DashboardData } from "@/types";

// ── Tooltip / axis shared styles ─────────────────────────────────────────────

const tooltipStyle = {
  contentStyle: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    fontSize: "12px",
    color: "var(--foreground)",
    padding: "8px 12px",
  },
  cursor: { stroke: "var(--border)", strokeWidth: 1 },
};

const axisStyle = {
  tick: { fontSize: 11, fill: "var(--muted-foreground)" },
  axisLine: { stroke: "var(--border)" },
  tickLine: false as const,
};

// ── KPI metric card ───────────────────────────────────────────────────────────

interface KPICardProps {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
  neutral?: boolean;
}

function KPICard({ label, value, sub, positive, neutral }: KPICardProps) {
  const valueColor = neutral || positive === undefined
    ? "text-foreground"
    : positive
    ? "text-success"
    : "text-destructive";

  return (
    <div className="rounded-lg border border-border/80 bg-card px-4 py-4 transition-colors hover:border-primary/30">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={cn("mt-2 text-xl font-semibold tabular tracking-tight sm:text-2xl", valueColor)}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground tabular">{sub}</p>}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: React.ElementType;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
    </div>
  );
}

// ── P&L Summary ───────────────────────────────────────────────────────────────

function PnLSummary({ pnl }: { pnl: DashboardData["pnl"] }) {
  const fmt = useCurrencyFormat();
  const netPositive = pnl.net_income >= 0;
  const ebitdaPositive = pnl.ebitda >= 0;

  return (
    <section aria-label="P&L Özeti">
      <SectionHeader icon={DollarSign} title="P&L Özeti" subtitle="Gelir, gider ve kâr analizi" />
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <KPICard
          label="Gelir (Revenue)"
          value={fmt(pnl.revenue)}
          neutral
        />
        <KPICard
          label="Brüt Kâr"
          value={fmt(pnl.gross_profit)}
          sub={formatPercent(pnl.gross_margin) + " marj"}
          positive={pnl.gross_profit >= 0}
        />
        <KPICard
          label="EBITDA"
          value={fmt(pnl.ebitda)}
          sub={formatPercent(pnl.ebitda_margin) + " marj"}
          positive={ebitdaPositive}
        />
        <KPICard
          label="Net Kâr"
          value={fmt(pnl.net_income)}
          sub={formatPercent(pnl.net_margin) + " marj"}
          positive={netPositive}
        />
        <KPICard
          label="Toplam COGS"
          value={fmt(pnl.cogs)}
          neutral
        />
      </div>

      {/* CFO narrative */}
      {pnl.narrative && (
        <div className="mt-3 rounded-lg border border-primary/20 bg-primary/[0.045] px-4 py-3">
          <p className="mb-1 text-xs font-semibold text-primary">CFO Yorumu</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {pnl.narrative}
          </p>
        </div>
      )}
    </section>
  );
}

// ── OpEx breakdown chart ──────────────────────────────────────────────────────

function OpExChart({ opex }: { opex: DashboardData["pnl"]["opex"] }) {
  const fmt = useCurrencyFormat();
  const symbol = useCurrencySymbol();
  const data = Object.entries(opex)
    .filter(([, v]) => v != null && v > 0)
    .map(([k, v]) => ({ name: k.replace(/_/g, " "), value: v ?? 0 }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  if (!data.length) {
    return (
      <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">
        Gider verisi yok
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
        <XAxis
          type="number"
          {...axisStyle}
          tickFormatter={(v: number) => `${symbol}${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`}
        />
        <YAxis dataKey="name" type="category" {...axisStyle} width={90} tick={{ ...axisStyle.tick, textAnchor: "end" }} />
        <Tooltip {...tooltipStyle} formatter={(v: number) => [fmt(v), "Tutar"]} />
        <Bar dataKey="value" fill="var(--chart-primary)" radius={[0, 3, 3, 0]} maxBarSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Cash flow section ─────────────────────────────────────────────────────────

function CashFlowSection({ cashflow }: { cashflow: DashboardData["cashflow"] }) {
  const fmt = useCurrencyFormat();
  const symbol = useCurrencySymbol();
  const netPositive = cashflow.net_change >= 0;
  const series = cashflow.monthly_series.map((m) => ({
    month: m.month.slice(5),
    in: m.in / 100,
    out: m.out / 100,
    net: m.net / 100,
  }));

  return (
    <section aria-label="Nakit Akışı">
      <SectionHeader icon={Waves} title="Nakit Akışı" subtitle="Aylık nakit giriş/çıkış analizi" />

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KPICard
          label="Net Değişim"
          value={fmt(cashflow.net_change)}
          positive={netPositive}
        />
        <KPICard
          label="Operasyonel"
          value={fmt(cashflow.operating)}
          positive={cashflow.operating >= 0}
        />
        <KPICard
          label="Yatırım"
          value={fmt(cashflow.investing)}
          positive={cashflow.investing >= 0}
        />
        <KPICard
          label="Finansman"
          value={fmt(cashflow.financing)}
          positive={cashflow.financing >= 0}
        />
      </div>

      {series.length > 1 && (
        <div className="mt-4 rounded-xl border border-border/80 bg-card p-4 sm:p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium">Aylık nakit hareketi</p>
            <div className="flex items-center gap-4 text-xs text-muted-foreground" aria-label="Grafik açıklaması">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-[color:var(--chart-primary)]" aria-hidden="true" />
                Giriş
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-[color:var(--chart-secondary)]" aria-hidden="true" />
                Çıkış
              </span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={series} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="cfo-gIn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-primary)" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="var(--chart-primary)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="cfo-gOut" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-secondary)" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="var(--chart-secondary)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis dataKey="month" {...axisStyle} />
              <YAxis {...axisStyle} tickFormatter={(v: number) => `${symbol}${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} />
              <Tooltip {...tooltipStyle} formatter={(v: number, name: string) => [fmt(v), name]} />
              <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeWidth={1} />
              <Area type="monotone" dataKey="in" name="Giriş" stroke="var(--chart-primary)" strokeWidth={2} fill="url(#cfo-gIn)" dot={false} />
              <Area type="monotone" dataKey="out" name="Çıkış" stroke="var(--chart-secondary)" strokeWidth={2} fill="url(#cfo-gOut)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Alerts */}
      {(cashflow.alerts ?? []).length > 0 && (
        <div className="mt-3 space-y-1.5">
          {(cashflow.alerts ?? []).map((a, i) => (
            <div
              key={i}
              role="alert"
              className={cn(
                "flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm",
                a.level === "critical"
                  ? "border-destructive/30 bg-destructive/8 text-destructive"
                  : "border-amber-500/25 bg-amber-500/6 text-amber-400"
              )}
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="leading-snug">{a.message}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Forecast section ──────────────────────────────────────────────────────────

function ForecastSection({ forecast }: { forecast: DashboardData["forecast"] }) {
  const fmt = useCurrencyFormat();
  const scenarios = Object.values(forecast.scenarios);
  if (!scenarios.length) return null;

  return (
    <section aria-label="Tahmin">
      <SectionHeader icon={TrendingUp} title="12 Aylık Tahmin" subtitle="Senaryo bazlı gelir tahmini" />
      <div className="mt-3 rounded-lg border border-border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" role="table">
            <thead>
              <tr className="border-b border-border">
                {["Senaryo", "12 Ay Net", "Nakit Süresi", "Varsayım"].map((h) => (
                  <th key={h} className={cn(
                    "px-4 py-2.5 text-xs font-medium text-muted-foreground",
                    h === "12 Ay Net" || h === "Nakit Süresi" ? "text-right" : "text-left"
                  )}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => {
                const isBase = s.label === "Base";
                const netPositive = s.twelve_month_net >= 0;
                return (
                  <tr
                    key={s.label}
                    className={cn(
                      "border-b border-border/50 last:border-0",
                      isBase ? "bg-primary/5" : "hover:bg-muted/30"
                    )}
                  >
                    <td className="px-4 py-3">
                      <span className={cn(
                        "inline-flex items-center gap-1.5 text-xs font-medium",
                        isBase ? "text-primary" : "text-muted-foreground"
                      )}>
                        {isBase && <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />}
                        {s.label}
                      </span>
                    </td>
                    <td className={cn(
                      "px-4 py-3 text-right tabular font-medium text-sm",
                      netPositive ? "text-success" : "text-destructive"
                    )}>
                      {(s.twelve_month_net >= 0 ? "+" : "")}{fmt(s.twelve_month_net)}
                    </td>
                    <td className="px-4 py-3 text-right tabular text-sm text-muted-foreground">
                      {s.runway_months != null ? `${s.runway_months} ay` : "Stabil"}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground max-w-[200px] hidden sm:table-cell">
                      {s.description}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {forecast.narrative && (
          <div className="border-t border-border/50 px-4 py-3">
            <p className="text-xs leading-relaxed text-muted-foreground max-w-prose">
              {forecast.narrative}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Reports section ───────────────────────────────────────────────────────────

function ReportsSection({ jobId }: { jobId: string }) {
  const { data: reports, isLoading } = useReports(jobId);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  if (!reports?.length) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        Henüz rapor üretilmedi. Analiz tamamlandığında raporlar burada görünür.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {reports.map((r) => (
        <div
          key={r.id}
          className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3"
        >
          <div className="flex items-center gap-3 min-w-0">
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{r.title ?? r.report_type}</p>
              <p className="text-xs text-muted-foreground">
                {new Date(r.created_at).toLocaleDateString("tr-TR")}
              </p>
            </div>
          </div>
          <a
            href="#"
            // A plain link cannot carry the session the download now requires.
            onClick={(e) => { e.preventDefault(); void downloadReport(r.id, r.report_type); }}
            className={cn(
              "ml-3 flex shrink-0 items-center gap-1.5 rounded-md border border-border",
              "px-3 py-1.5 text-xs font-medium text-muted-foreground",
              "transition-colors hover:border-primary/30 hover:text-primary"
            )}
            aria-label={`${r.title ?? r.report_type} indir`}
          >
            <Download className="h-3 w-3" aria-hidden="true" />
            İndir
          </a>
        </div>
      ))}
    </div>
  );
}

// ── Alerts section ────────────────────────────────────────────────────────────

function AlertsSection({ jobId }: { jobId: string | null }) {
  const { data: topAlertsData } = useTopAlerts(jobId);
  if (!topAlertsData?.top_alerts?.length) return null;

  return (
    <section aria-label="Kritik Uyarılar">
      <SectionHeader
        icon={ShieldAlert}
        title="Kritik Uyarılar"
        subtitle="Öncelikli aksiyon gerektiren konular"
      />
      <div className="mt-3 space-y-2">
        {topAlertsData.top_alerts.map((alert, i) => (
          <div
            key={i}
            className={cn(
              "rounded-lg border px-3.5 py-3 text-sm",
              alert.level === "critical"
                ? "border-destructive/30 bg-destructive/8"
                : "border-amber-500/25 bg-amber-500/6"
            )}
          >
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  "mt-1 h-1.5 w-1.5 rounded-full shrink-0",
                  alert.level === "critical" ? "bg-destructive" : "bg-amber-400"
                )}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className={cn(
                  "font-medium leading-snug",
                  alert.level === "critical" ? "text-destructive" : "text-amber-400"
                )}>
                  {alert.message}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">→ {alert.action}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function CFOSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8" aria-busy="true" aria-label="CFO verisi yükleniyor">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="h-64 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function CFOEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">CFO analizi için veri gerekli</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Banka ekstresi, fatura CSV veya Excel dosyası yükleyin — AI CFO analizinizi saniyeler içinde hazırlar.
      </p>
      <Link
        href="/upload"
        className={cn(
          "mt-5 flex items-center gap-1.5 rounded-md bg-primary px-4 py-2",
          "text-sm font-medium text-primary-foreground",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Veri Yükle
        <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CFOPage() {
  const searchParams = useSearchParams();
  const urlJobId = searchParams.get("job");
  const contextJobId = useActiveCFOJob();
  const jobId = urlJobId ?? contextJobId;

  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) return <CFOEmptyState />;
  if (isLoading) return <CFOSkeleton />;
  if (!dashboard) return <CFOEmptyState />;

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-8 p-4 sm:p-6 xl:p-8">

      {/* Page header */}
      <div className="flex flex-col justify-between gap-5 border-b border-border/80 pb-6 sm:flex-row sm:items-end">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">CFO Görünümü</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Finansal performans, nakit pozisyonu ve öncelikli konular.
          </p>
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="tabular-nums">{dashboard.transaction_count} işlem</span>
            <span aria-hidden="true" className="text-border">/</span>
            <span>Son analiz {new Date(dashboard.generated_at).toLocaleString("tr-TR")}</span>
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Link
            href={`/pnl?job=${jobId}`}
            className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-card/60 px-3.5 text-xs font-medium text-foreground/80 transition-colors hover:border-primary/40 hover:bg-card hover:text-foreground"
          >
            <BarChart2 className="h-3.5 w-3.5" aria-hidden="true" />
            P&L Detay
          </Link>
          <Link
            href={`/cashflow?job=${jobId}`}
            className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-card/60 px-3.5 text-xs font-medium text-foreground/80 transition-colors hover:border-primary/40 hover:bg-card hover:text-foreground"
          >
            <Waves className="h-3.5 w-3.5" aria-hidden="true" />
            Nakit akışı
          </Link>
        </div>
      </div>

      {/* Alerts — top priority */}
      <AlertsSection jobId={jobId} />

      {/* P&L Summary */}
      <PnLSummary pnl={dashboard.pnl} />

      {/* Charts — OpEx + trend */}
      <section aria-label="Gider Analizi">
        <SectionHeader icon={Activity} title="Gider Dağılımı" subtitle="Kategorilere göre operasyonel giderler" />
        <div className="mt-3 rounded-lg border border-border bg-card p-4">
          <OpExChart opex={dashboard.pnl.opex} />
        </div>
      </section>

      {/* Cash Flow */}
      <CashFlowSection cashflow={dashboard.cashflow} />

      {/* Forecast */}
      {dashboard.forecast?.scenarios && Object.keys(dashboard.forecast.scenarios).length > 0 && (
        <ForecastSection forecast={dashboard.forecast} />
      )}

      {/* Reports */}
      <section aria-label="Raporlar">
        <div className="flex items-center justify-between">
          <SectionHeader icon={FileText} title="Raporlar" subtitle="İndirilebilir Excel / PDF raporlar" />
          <Link
            href={`/reports?job=${jobId}`}
            className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Tümü
            <ChevronRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        </div>
        <div className="mt-3">
          <ReportsSection jobId={jobId} />
        </div>
      </section>

      {/* Navigation links to related views */}
      <section aria-label="İlgili analizler">
        <p className="mb-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Bağlı Analizler
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {[
            { href: `/forecast?job=${jobId}`,    icon: TrendingUp,   label: "Tahmin" },
            { href: `/budget?job=${jobId}`,      icon: DollarSign,   label: "Bütçe" },
            { href: `/anomalies?job=${jobId}`,   icon: ShieldAlert,  label: "Anomaliler" },
            { href: `/tax?job=${jobId}`,         icon: FileText,     label: "Vergi" },
            { href: `/sensitivity?job=${jobId}`, icon: Activity,     label: "What-If" },
            { href: `/comparison?job=${jobId}`,  icon: BarChart2,    label: "Karşılaştırma" },
            { href: `/ceo?job=${jobId}`,         icon: TrendingUp,   label: "CEO Özeti" },
            { href: `/risk?job=${jobId}`,        icon: ShieldAlert,  label: "Risk" },
          ].map(({ href, icon: Icon, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5",
                "text-sm text-muted-foreground transition-colors",
                "hover:border-primary/20 hover:bg-primary/5 hover:text-foreground"
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {label}
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
