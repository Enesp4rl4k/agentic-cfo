"use client";

import { useSearchParams } from "next/navigation";
import { Calendar, AlertCircle, Upload, TrendingDown } from "lucide-react";
import { useDashboard } from "@/hooks/useCFO";
import { formatCurrency, cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface PaymentItem {
  type: string;
  due_date: string;
  amount: number;
  description: string;
}

interface TaxData {
  vat: { output_vat: number; input_vat: number; net_vat_payable: number };
  withholding: {
    salary_base: number;
    income_tax_withholding: number;
    ssi_employer: number;
    total_payroll_tax: number;
  };
  corporate: {
    taxable_income: number;
    corporate_tax_estimate: number;
    effective_rate: number;
  };
  payment_calendar: PaymentItem[];
  total_tax_burden: number;
  reference_month: string;
  narrative: string;
}

// ── Summary KPI strip ─────────────────────────────────────────────────────────

function TaxKPIStrip({ tax }: { tax: TaxData }) {
  const items = [
    {
      label: "KDV (Net)",
      value: formatCurrency(tax.vat.net_vat_payable / 100),
      sub: `Çıktı: ${formatCurrency(tax.vat.output_vat / 100)} / Girdi: ${formatCurrency(tax.vat.input_vat / 100)}`,
      color: "text-foreground",
    },
    {
      label: "Stopaj",
      value: formatCurrency(tax.withholding.income_tax_withholding / 100),
      sub: `Maaş tabanı: ${formatCurrency(tax.withholding.salary_base / 100)}`,
      color: "text-foreground",
    },
    {
      label: "SGK İşveren",
      value: formatCurrency(tax.withholding.ssi_employer / 100),
      sub: "Toplam bordro yükü dahil",
      color: "text-foreground",
    },
    {
      label: "Kurumlar Vergisi",
      value: formatCurrency(tax.corporate.corporate_tax_estimate / 100),
      sub: `Efektif oran: ${tax.corporate.effective_rate}%`,
      color: "text-foreground",
    },
    {
      label: "Toplam Vergi Yükü",
      value: formatCurrency(tax.total_tax_burden / 100),
      sub: tax.reference_month,
      color: "text-destructive",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-5">
      {items.map((item) => (
        <div key={item.label} className="bg-card px-4 py-4">
          <p className="text-xs text-muted-foreground">{item.label}</p>
          <p className={cn("mt-1 text-base font-semibold tabular-nums tracking-tight", item.color)}>
            {item.value}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{item.sub}</p>
        </div>
      ))}
    </div>
  );
}

// ── Payment calendar ──────────────────────────────────────────────────────────

function PaymentCalendar({ payments }: { payments: PaymentItem[] }) {
  if (!payments.length) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
        Yaklaşan vergi ödemesi bulunmuyor.
      </div>
    );
  }

  const today = new Date();

  return (
    <div className="space-y-2">
      {payments.map((p, i) => {
        const due = new Date(p.due_date);
        const daysUntil = Math.ceil((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
        const isUrgent = daysUntil <= 3;
        const isNear = daysUntil <= 14;

        return (
          <div
            key={i}
            className={cn(
              "flex items-center gap-4 rounded-lg border px-4 py-3",
              isUrgent
                ? "border-destructive/30 bg-destructive/8"
                : isNear
                ? "border-yellow-600/25 bg-yellow-950/15"
                : "border-border bg-card"
            )}
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Calendar
                className={cn(
                  "h-4 w-4",
                  isUrgent ? "text-destructive" : isNear ? "text-yellow-400" : "text-muted-foreground"
                )}
                aria-hidden="true"
              />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">{p.type}</p>
              <p className="text-xs text-muted-foreground">{p.description}</p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-sm font-semibold tabular-nums">{formatCurrency(p.amount / 100)}</p>
              <p
                className={cn(
                  "text-xs tabular-nums",
                  isUrgent ? "text-destructive" : isNear ? "text-yellow-400" : "text-muted-foreground"
                )}
              >
                {daysUntil > 0 ? `${daysUntil} gün kaldı` : daysUntil === 0 ? "Bugün!" : "Geçti"}
                {" · "}{p.due_date}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Breakdown table ───────────────────────────────────────────────────────────

function TaxBreakdown({ tax }: { tax: TaxData }) {
  const rows = [
    { label: "Çıktı KDV (Satışlardan)", amount: tax.vat.output_vat, positive: false },
    { label: "Girdi KDV (Alışlardan, indirim)", amount: -tax.vat.input_vat, positive: true },
    { label: "Net KDV Borcu", amount: tax.vat.net_vat_payable, bold: true, positive: false },
    { label: "", amount: null },
    { label: "Brüt Maaş Ödemeleri", amount: tax.withholding.salary_base, positive: false },
    { label: "Gelir Vergisi Stopajı (%15)", amount: tax.withholding.income_tax_withholding, positive: false },
    { label: "SGK İşveren Payı (%22.5)", amount: tax.withholding.ssi_employer, positive: false },
    { label: "Toplam Bordro Vergi Yükü", amount: tax.withholding.total_payroll_tax, bold: true, positive: false },
    { label: "", amount: null },
    { label: "Vergilendirilebilir Gelir", amount: tax.corporate.taxable_income, positive: false },
    { label: "Kurumlar Vergisi Tahmini (%25)", amount: tax.corporate.corporate_tax_estimate, bold: true, positive: false },
  ] as const;

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Vergi Detay Dökümü</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {tax.reference_month} dönemi tahmini vergi yükümlülükleri
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Kalem</th>
              <th className="px-4 py-2.5 text-right text-xs font-medium text-muted-foreground">Tutar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              if (row.amount === null) {
                return (
                  <tr key={i}>
                    <td colSpan={2} className="px-4 py-1">
                      <div className="border-t border-border/40" />
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={i} className="hover:bg-muted/10 transition-colors">
                  <td className={cn("px-4 py-2 text-sm", "bold" in row && row.bold ? "font-semibold" : "text-muted-foreground")}>
                    {row.label}
                  </td>
                  <td className={cn(
                    "px-4 py-2 text-right tabular-nums text-sm",
                    "bold" in row && row.bold ? "font-semibold" : "",
                    row.positive ? "text-emerald-400" : "text-foreground"
                  )}>
                    {row.positive && row.amount < 0 ? "+" : ""}
                    {formatCurrency(Math.abs(row.amount) / 100)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-6">
      <div className="mb-4 rounded-full bg-muted p-4">
        <Upload className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold">Vergi verisi yok</h2>
      <p className="mt-1.5 max-w-xs text-sm text-muted-foreground leading-relaxed">
        Finansal belge yükleyip analiz ettirin, vergi hesaplamaları otomatik yapılır.
      </p>
      <a href="/upload" className={cn(
        "mt-5 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
        "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}>
        Belge yükle
      </a>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TaxPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const { data: dashboard, isLoading } = useDashboard(jobId);

  if (!jobId || (!isLoading && !dashboard)) return <EmptyState />;

  if (isLoading) {
    return (
      <div className="space-y-4 p-5">
        <div className="h-6 w-40 animate-pulse rounded bg-muted" />
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-5">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-card px-4 py-4">
              <div className="h-3 w-16 animate-pulse rounded bg-muted" />
              <div className="mt-2 h-5 w-24 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const tax = (dashboard as any)?.tax as TaxData | null | undefined;

  if (!tax) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center px-6">
        <div className="mb-4 rounded-full bg-muted p-4">
          <AlertCircle className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        </div>
        <h2 className="text-base font-semibold">Vergi hesaplaması bulunamadı</h2>
        <p className="mt-1.5 max-w-xs text-sm text-muted-foreground">
          Bu analiz için vergi verisi mevcut değil. Yeniden analiz edin.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Vergi Analizi</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {tax.reference_month} dönemi · KDV, stopaj ve kurumlar vergisi tahmini
        </p>
      </div>

      <TaxKPIStrip tax={tax} />

      {tax.narrative && (
        <div className="rounded-lg border border-border bg-card px-4 py-3.5">
          <p className="mb-1 text-xs font-medium text-primary">Vergi Danışmanı Yorumu</p>
          <p className="text-sm leading-relaxed text-muted-foreground max-w-prose">
            {tax.narrative}
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TaxBreakdown tax={tax} />

        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">Ödeme Takvimi</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Yaklaşan vergi yükümlülükleri ve son ödeme tarihleri
            </p>
          </div>
          <div className="p-4">
            <PaymentCalendar payments={tax.payment_calendar} />
          </div>
        </div>
      </div>
    </div>
  );
}
