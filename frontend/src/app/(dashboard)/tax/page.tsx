"use client";

import { useSearchParams } from "next/navigation";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";

const axisStyle = {
  tick: { fontSize: 11, fill: "oklch(0.52 0.012 255)" },
  axisLine: { stroke: "oklch(0.27 0.018 255)" },
  tickLine: false as const,
};

const tooltipStyle = {
  contentStyle: {
    background: "oklch(0.17 0.022 255)",
    border: "1px solid oklch(0.27 0.018 255)",
    borderRadius: "6px",
    fontSize: "12px",
    color: "oklch(0.92 0.008 255)",
    padding: "8px 12px",
  },
};

function TaxCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: "warning" | "info" | "neutral";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card px-4 py-4",
        highlight === "warning"
          ? "border-warning/30"
          : highlight === "info"
          ? "border-primary/20"
          : "border-border"
      )}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-lg font-semibold tabular tracking-tight",
          highlight === "warning"
            ? "text-warning"
            : highlight === "info"
            ? "text-primary"
            : "text-foreground"
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

export default function TaxPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">No job selected. Upload a document first.</p>
      </div>
    );
  }

  if (isLoading || !dashboard) {
    return (
      <div className="space-y-4 p-5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  const tax = dashboard.tax_analysis;
  if (!tax) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <p className="text-sm text-muted-foreground">
          Tax analysis not available for this job.
        </p>
      </div>
    );
  }

  const kdvChartData = tax.monthly_kdv.map((m) => ({
    month: m.month.slice(5),
    collected: m.collected / 100,
    paid: m.paid / 100,
    net: m.net / 100,
  }));

  return (
    <div className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold">Vergi Analizi</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          KDV · Stopaj · Kurumlar Vergisi tahmini
        </p>
      </div>

      {/* Alerts */}
      {tax.alerts?.map((a, i) => (
        <div
          key={i}
          role="alert"
          className={cn(
            "flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-sm",
            a.level === "critical"
              ? "border-destructive/30 bg-destructive/8 text-destructive"
              : a.level === "warning"
              ? "border-warning/25 bg-warning/6 text-warning"
              : "border-border bg-muted/30 text-muted-foreground"
          )}
        >
          {a.message}
        </div>
      ))}

      {/* KDV section */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-muted-foreground uppercase tracking-wide">
          KDV (Katma Değer Vergisi)
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <TaxCard label="KDV Tahsil Edilen" value={formatCurrency(tax.kdv_collected)} highlight="neutral" />
          <TaxCard label="KDV Ödenen" value={formatCurrency(tax.kdv_paid)} highlight="neutral" />
          <TaxCard
            label="Ödenecek KDV"
            value={formatCurrency(tax.kdv_payable)}
            sub={tax.kdv_payable > 0 ? "Vergi dairesine ödenecek" : "Ödeme yok"}
            highlight={tax.kdv_payable > 0 ? "warning" : "neutral"}
          />
          <TaxCard
            label="KDV İade Hakkı"
            value={formatCurrency(tax.kdv_refundable)}
            sub={tax.kdv_refundable > 0 ? "İade başvurusu yapılabilir" : "İade yok"}
            highlight={tax.kdv_refundable > 0 ? "info" : "neutral"}
          />
        </div>
      </div>

      {/* Monthly KDV chart */}
      {kdvChartData.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-0.5 text-sm font-medium">Aylık KDV Analizi</h3>
          <p className="mb-4 text-xs text-muted-foreground">Tahsil edilen vs ödenen KDV</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={kdvChartData} margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.22 0.018 255)" vertical={false} />
              <XAxis dataKey="month" {...axisStyle} />
              <YAxis
                {...axisStyle}
                tickFormatter={(v: number) =>
                  `₺${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`
                }
              />
              <Tooltip
                {...tooltipStyle}
                formatter={(v: number, name: string) => [formatCurrency(v), name]}
              />
              <Bar dataKey="collected" name="Tahsil Edilen" fill="oklch(0.60 0.19 142)" maxBarSize={24} radius={[2, 2, 0, 0]} />
              <Bar dataKey="paid" name="Ödenen" fill="oklch(0.60 0.19 255)" maxBarSize={24} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Stopaj section */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-muted-foreground uppercase tracking-wide">
          Stopaj (Withholding Tax)
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <TaxCard label="Maaş Stopajı (%20)" value={formatCurrency(tax.stopaj_salary)} sub="Aylık muhtasar" highlight="warning" />
          <TaxCard label="Kira Stopajı (%20)" value={formatCurrency(tax.stopaj_rent)} sub="Aylık muhtasar" highlight="warning" />
          <TaxCard label="Toplam Stopaj" value={formatCurrency(tax.stopaj_total)} sub="Toplam yükümlülük" highlight="warning" />
        </div>
      </div>

      {/* Kurumlar Vergisi section */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-muted-foreground uppercase tracking-wide">
          Kurumlar Vergisi (%25)
        </h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <TaxCard label="Vergiye Tabi Gelir" value={formatCurrency(tax.kurumlar_vergisi_annual * 4)} highlight="neutral" />
          <TaxCard
            label="Yıllık Kurumlar Vergisi"
            value={formatCurrency(tax.kurumlar_vergisi_annual)}
            sub="%25 oran"
            highlight="warning"
          />
          <TaxCard
            label="Geçici Vergi (Çeyrek)"
            value={formatCurrency(tax.gecici_vergi_quarterly)}
            sub="Her çeyrekte ödenir"
            highlight="info"
          />
        </div>
      </div>

      {/* Total tax burden */}
      <div className="rounded-lg border border-warning/20 bg-warning/5 px-4 py-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Toplam Tahmini Vergi Yükü</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Efektif vergi oranı: %{(tax.effective_tax_rate * 100).toFixed(1)} (gelire göre)
            </p>
          </div>
          <p className="text-xl font-bold tabular text-warning">
            {formatCurrency(tax.total_tax_burden)}
          </p>
        </div>
      </div>

      {/* Narrative */}
      {tax.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">Mali Müşavir Yorumu</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {tax.narrative}
          </p>
        </div>
      )}
    </div>
  );
}
