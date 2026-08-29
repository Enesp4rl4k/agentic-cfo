"use client";

import { cn } from "@/lib/utils";

/**
 * Provenance badge for C-level kernel metrics.
 *
 * Several C-level views (CTO / CHRO / CMO / COO, partly Risk / Audit) synthesise
 * their numbers from CFO financials × fixed sector benchmarks when no real domain
 * data source is connected. This badge makes that basis unmissable so a reader
 * never mistakes an extrapolation for a measurement.
 */

type Tone = "real" | "estimated" | "benchmark" | "rule";

const MAP: Record<string, { tone: Tone; label: string; hint: string }> = {
  real: {
    tone: "real",
    label: "Bağlı veri",
    hint: "Bağlı entegrasyon veya elle girilen alan verisinden hesaplandı.",
  },
  estimated: {
    tone: "estimated",
    label: "CFO'dan tahmin",
    hint: "Bağlı bir alan verisi yok — CFO finansallarından sektör oranlarıyla tahmin edildi.",
  },
  benchmark: {
    tone: "benchmark",
    label: "Sektör varsayımı — analiz değil",
    hint: "Ölçüm yok. Rakamlar sektör benchmark sabitlerinden üretildi; karar dayanağı olarak kullanmayın.",
  },
  derived: {
    tone: "benchmark",
    label: "Türetilmiş — analiz değil",
    hint: "Diğer ajanların çıktılarından çıkarsandı; bağımsız bir ölçüm değildir.",
  },
  rule_based: {
    tone: "rule",
    label: "Kural tabanlı",
    hint: "Deterministik mevzuat/kontrol listesi değerlendirmesi.",
  },
};

const TONE_CLASS: Record<Tone, string> = {
  real: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  estimated: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  benchmark: "border-red-500/40 bg-red-500/10 text-red-400",
  rule: "border-border bg-muted/30 text-muted-foreground",
};

export function ProvenanceBadge({
  dataSource,
  confidence,
  className,
}: {
  dataSource: string | null | undefined;
  confidence?: number | null;
  className?: string;
}) {
  const key = (dataSource || "benchmark").toLowerCase();
  const entry = MAP[key] ?? MAP.benchmark;
  const pct =
    typeof confidence === "number" ? ` · güven %${Math.round(confidence * 100)}` : "";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        TONE_CLASS[entry.tone],
        className
      )}
      title={`${entry.hint}${pct ? ` (güven: %${Math.round((confidence as number) * 100)})` : ""}`}
    >
      {entry.label}
      {pct}
    </span>
  );
}
