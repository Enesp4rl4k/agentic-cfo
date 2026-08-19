"use client";

import { useState } from "react";
import {
  ChevronDown, ChevronUp, Info, Search, Scale,
  TrendingUp, AlertTriangle, FileText, Database,
  CheckCircle2, XCircle, HelpCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { AnomalyItem } from "@/lib/api/cfo";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EvidenceField {
  key:   string;
  value: unknown;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseEvidence(evidence: Record<string, unknown> | null): EvidenceField[] {
  if (!evidence) return [];
  return Object.entries(evidence).map(([key, value]) => ({ key, value }));
}

function formatEvidenceKey(key: string): string {
  const labels: Record<string, string> = {
    z_score:          "Z-Skoru",
    zscore:           "Z-Skoru",
    amount:           "Tutar",
    expected_amount:  "Beklenen Tutar",
    expected_range:   "Beklenen Aralık",
    actual_value:     "Gerçekleşen Değer",
    comparison_value: "Karşılaştırma Değeri",
    category:         "Kategori",
    vendor:           "Tedarikçi",
    transaction_date: "İşlem Tarihi",
    method:           "Tespit Yöntemi",
    threshold:        "Eşik Değer",
    std_dev:          "Standart Sapma",
    mean:             "Ortalama",
    frequency:        "Frekans",
    pattern:          "Örüntü",
    rule:             "Kural",
    similar_count:    "Benzer İşlem Sayısı",
    sample_size:      "Örnek Büyüklüğü",
    confidence_basis: "Güven Temeli",
    data_source:      "Veri Kaynağı",
  };
  return labels[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatEvidenceValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "number") {
    // Currency-like fields
    if (["amount", "expected_amount", "actual_value", "comparison_value"].includes(key)) {
      return `₺${(value / 100).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`;
    }
    // Z-score: show with 2 decimals
    if (["z_score", "zscore", "std_dev"].includes(key)) {
      return value.toFixed(2);
    }
    // Percentage-like
    if (key.includes("pct") || key.includes("rate") || key.includes("percent")) {
      return `%${(value * 100).toFixed(1)}`;
    }
    return value.toLocaleString("tr-TR");
  }
  if (typeof value === "object") return JSON.stringify(value, null, 0).slice(0, 100);
  return String(value);
}

function getEvidenceIcon(key: string) {
  if (key.includes("z_score") || key.includes("zscore") || key.includes("std"))
    return <Scale className="h-3 w-3 text-blue-400" />;
  if (key.includes("amount") || key.includes("value") || key.includes("expected"))
    return <TrendingUp className="h-3 w-3 text-emerald-400" />;
  if (key.includes("method") || key.includes("rule") || key.includes("pattern"))
    return <Search className="h-3 w-3 text-purple-400" />;
  if (key.includes("source") || key.includes("data"))
    return <Database className="h-3 w-3 text-cyan-400" />;
  return <FileText className="h-3 w-3 text-muted-foreground" />;
}

// ── Confidence meter ──────────────────────────────────────────────────────────

function ConfidenceMeter({ confidence }: { confidence: number | null }) {
  if (confidence === null) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <HelpCircle className="h-3 w-3" />
        Güven skoru bilinmiyor
      </div>
    );
  }

  const pct = Math.round(confidence * 100);
  const color =
    pct >= 80 ? "bg-red-500" :
    pct >= 60 ? "bg-orange-400" :
    pct >= 40 ? "bg-yellow-400" : "bg-blue-400";

  const label =
    pct >= 80 ? "Yüksek Güven" :
    pct >= 60 ? "Orta Güven" :
    pct >= 40 ? "Düşük Güven" : "Belirsiz";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">AI Güven Skoru</span>
        <span className={cn("font-semibold tabular-nums", pct >= 80 ? "text-red-400" : pct >= 60 ? "text-orange-400" : "text-yellow-400")}>
          %{pct} — {label}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Z-Score interpretation ────────────────────────────────────────────────────

function ZScoreInterpretation({ zscore }: { zscore: number }) {
  const abs = Math.abs(zscore);
  const direction = zscore > 0 ? "normalden yüksek" : "normalden düşük";
  const interpretation =
    abs >= 3 ? { label: "Çok Anormal", color: "text-red-400",    bg: "bg-red-500/10" } :
    abs >= 2 ? { label: "Anormal",     color: "text-orange-400", bg: "bg-orange-500/10" } :
    abs >= 1 ? { label: "Sınırda",     color: "text-yellow-400", bg: "bg-yellow-500/10" } :
               { label: "Normal",      color: "text-emerald-400",bg: "bg-emerald-500/10" };

  return (
    <div className={cn("rounded-md px-2.5 py-1.5 text-xs space-y-0.5", interpretation.bg)}>
      <div className="flex items-center justify-between">
        <span className={cn("font-semibold", interpretation.color)}>{interpretation.label}</span>
        <span className="font-mono tabular-nums">{zscore.toFixed(2)}σ</span>
      </div>
      <p className="text-muted-foreground">
        Bu değer ortalamanın {abs.toFixed(1)} standart sapma {direction}.
        {abs >= 3 ? " İstatistiksel olarak son derece nadir." :
         abs >= 2 ? " İstatistiksel olarak olası değil." :
         abs >= 1 ? " Dikkat gerektiriyor." : " Normal dağılım içinde."}
      </p>
    </div>
  );
}

// ── Evidence chain panel ──────────────────────────────────────────────────────

interface EvidenceChainPanelProps {
  anomaly:   AnomalyItem;
  className?: string;
}

export function EvidenceChainPanel({ anomaly, className }: EvidenceChainPanelProps) {
  const [open, setOpen] = useState(false);
  const fields = parseEvidence(anomaly.evidence);

  // Extract z-score for special rendering
  const zscoreField = fields.find((f) => f.key === "z_score" || f.key === "zscore");
  const zscoreValue = zscoreField ? Number(zscoreField.value) : null;
  const otherFields = fields.filter((f) => f.key !== "z_score" && f.key !== "zscore");

  const hasEvidence = fields.length > 0 || anomaly.confidence !== null;

  if (!hasEvidence) {
    return (
      <div className={cn("rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground flex items-center gap-1.5", className)}>
        <Info className="h-3 w-3 shrink-0" />
        Bu anomali için kanıt verisi mevcut değil
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border border-border bg-card overflow-hidden", className)}>
      {/* Toggle header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-muted/30 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          <Search className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs font-semibold">Kanıt Zinciri</span>
          {fields.length > 0 && (
            <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary font-medium">
              {fields.length} kanıt
            </span>
          )}
        </div>
        {open ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
      </button>

      {/* Content */}
      {open && (
        <div className="border-t border-border px-3 py-3 space-y-3">
          {/* Confidence meter */}
          <ConfidenceMeter confidence={anomaly.confidence} />

          {/* Z-score interpretation */}
          {zscoreValue !== null && !isNaN(zscoreValue) && (
            <ZScoreInterpretation zscore={zscoreValue} />
          )}

          {/* Detection method chain */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Kanıt Detayları
            </p>
            <div className="space-y-1">
              {/* Anomaly type as first step */}
              <div className="flex items-start gap-2 text-xs">
                <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/15">
                  <span className="text-[9px] font-bold text-primary">1</span>
                </div>
                <div>
                  <p className="font-medium">Tespit Tipi</p>
                  <p className="text-muted-foreground capitalize">{anomaly.anomaly_type.replace(/_/g, " ")}</p>
                </div>
              </div>

              {/* Evidence fields */}
              {otherFields.map((field, i) => (
                <div key={field.key} className="flex items-start gap-2 text-xs">
                  <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-muted">
                    <span className="text-[9px] font-bold text-muted-foreground">{i + 2}</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      {getEvidenceIcon(field.key)}
                      <p className="font-medium">{formatEvidenceKey(field.key)}</p>
                    </div>
                    <p className="text-muted-foreground font-mono tabular-nums">
                      {formatEvidenceValue(field.key, field.value)}
                    </p>
                  </div>
                </div>
              ))}

              {/* Conclusion */}
              <div className="flex items-start gap-2 text-xs">
                <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-orange-500/15">
                  <AlertTriangle className="h-2.5 w-2.5 text-orange-400" />
                </div>
                <div>
                  <p className="font-medium">Sonuç</p>
                  <p className="text-muted-foreground">{anomaly.description}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Transaction IDs */}
          {anomaly.transaction_ids && anomaly.transaction_ids.length > 0 && (
            <div className="space-y-1">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
                İlgili İşlemler ({anomaly.transaction_ids.length})
              </p>
              <div className="flex flex-wrap gap-1">
                {anomaly.transaction_ids.slice(0, 8).map((id) => (
                  <span key={id} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {id.slice(0, 8)}…
                  </span>
                ))}
                {anomaly.transaction_ids.length > 8 && (
                  <span className="text-[10px] text-muted-foreground">+{anomaly.transaction_ids.length - 8} daha</span>
                )}
              </div>
            </div>
          )}

          {/* Acknowledgment status */}
          <div className="flex items-center gap-1.5 border-t border-border pt-2 text-xs">
            {anomaly.acknowledged ? (
              <>
                <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                <span className="text-emerald-400">Onaylandı</span>
                {anomaly.acknowledged_at && (
                  <span className="text-muted-foreground">
                    — {new Date(anomaly.acknowledged_at).toLocaleString("tr-TR")}
                  </span>
                )}
              </>
            ) : (
              <>
                <XCircle className="h-3 w-3 text-orange-400" />
                <span className="text-orange-400">Henüz incelenmedi</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Compact inline badge (for table rows) ─────────────────────────────────────

export function ConfidenceBadge({ confidence }: { confidence: number | null }) {
  if (confidence === null) return null;
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 80 ? "bg-red-500/15 text-red-400 border-red-500/20" :
    pct >= 60 ? "bg-orange-500/15 text-orange-400 border-orange-500/20" :
    pct >= 40 ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/20" :
                "bg-blue-500/15 text-blue-400 border-blue-500/20";

  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-medium tabular-nums", color)}>
      <Scale className="h-2.5 w-2.5" />
      %{pct}
    </span>
  );
}
