"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  TrendingUp, TrendingDown, AlertTriangle, Zap,
  ChevronDown, ChevronUp, RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SWOTData {
  strengths:    string[];
  weaknesses:   string[];
  opportunities: string[];
  threats:      string[];
  strategic_priorities?: string[];
  summary?: string;
}

// ── Quadrant config ───────────────────────────────────────────────────────────

const QUADRANTS = [
  {
    key:       "strengths" as const,
    label:     "Güçlü Yönler",
    icon:      TrendingUp,
    color:     "text-emerald-400",
    bg:        "bg-emerald-500/5 border-emerald-500/20",
    headerBg:  "bg-emerald-500/10",
    bullet:    "bg-emerald-400",
    abbr:      "S",
  },
  {
    key:       "weaknesses" as const,
    label:     "Zayıf Yönler",
    icon:      TrendingDown,
    color:     "text-red-400",
    bg:        "bg-red-500/5 border-red-500/20",
    headerBg:  "bg-red-500/10",
    bullet:    "bg-red-400",
    abbr:      "W",
  },
  {
    key:       "opportunities" as const,
    label:     "Fırsatlar",
    icon:      Zap,
    color:     "text-blue-400",
    bg:        "bg-blue-500/5 border-blue-500/20",
    headerBg:  "bg-blue-500/10",
    bullet:    "bg-blue-400",
    abbr:      "O",
  },
  {
    key:       "threats" as const,
    label:     "Tehditler",
    icon:      AlertTriangle,
    color:     "text-orange-400",
    bg:        "bg-orange-500/5 border-orange-500/20",
    headerBg:  "bg-orange-500/10",
    bullet:    "bg-orange-400",
    abbr:      "T",
  },
] as const;

// ── Single quadrant card ──────────────────────────────────────────────────────

function SWOTQuadrant({
  quadrant, items,
}: {
  quadrant: typeof QUADRANTS[number];
  items: string[];
}) {
  const Icon = quadrant.icon;
  const [expanded, setExpanded] = useState(true);

  return (
    <div className={cn("rounded-lg border overflow-hidden", quadrant.bg)}>
      {/* Header */}
      <div className={cn("flex items-center justify-between px-3 py-2", quadrant.headerBg)}>
        <div className="flex items-center gap-1.5">
          <span className={cn(
            "flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold",
            quadrant.color
          )}>
            {quadrant.abbr}
          </span>
          <Icon className={cn("h-3.5 w-3.5", quadrant.color)} />
          <span className={cn("text-xs font-semibold", quadrant.color)}>{quadrant.label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground">{items.length} madde</span>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-muted-foreground hover:text-foreground"
            aria-label={expanded ? "Daralt" : "Genişlet"}
          >
            {expanded
              ? <ChevronUp className="h-3 w-3" />
              : <ChevronDown className="h-3 w-3" />
            }
          </button>
        </div>
      </div>

      {/* Items */}
      {expanded && (
        <div className="p-3 space-y-1.5">
          {items.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">Veri yok</p>
          ) : (
            items.map((item, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", quadrant.bullet)} />
                <p className="text-xs leading-relaxed text-foreground/90">{item}</p>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Strategic priorities strip ────────────────────────────────────────────────

function StrategicPriorities({ priorities }: { priorities: string[] }) {
  if (!priorities.length) return null;
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 space-y-2">
      <p className="text-xs font-semibold text-primary">Stratejik Öncelikler</p>
      <div className="space-y-1.5">
        {priorities.map((p, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="mt-0.5 shrink-0 rounded-sm bg-primary/20 px-1 text-[9px] font-bold text-primary">
              {i + 1}
            </span>
            <p className="text-xs text-muted-foreground leading-relaxed">{p}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main SWOT Widget ──────────────────────────────────────────────────────────

interface SWOTWidgetProps {
  /** Pre-loaded SWOT data (from CEO pipeline result) */
  data?: SWOTData | null;
  /** Job ID to fetch SWOT from API if data not provided */
  jobId?: string | null;
  /** Org ID fallback */
  orgId?: string | null;
  className?: string;
}

export function SWOTWidget({ data: initialData, jobId, orgId, className }: SWOTWidgetProps) {
  const [swot, setSwot]       = useState<SWOTData | null>(initialData ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function fetchSwot() {
    if (!jobId && !orgId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<{
        swot: SWOTData;
        strategic_priorities?: string[];
      }>("/swot/analyze", { job_id: jobId, org_id: orgId });

      const result = res.data.swot ?? res.data as unknown as SWOTData;
      setSwot({
        ...result,
        strategic_priorities: res.data.strategic_priorities ?? result.strategic_priorities ?? [],
      });
    } catch (err) {
      setError("SWOT analizi yüklenemedi");
    } finally {
      setLoading(false);
    }
  }

  // Sample data for when no real data is available
  const SAMPLE: SWOTData = {
    strengths:     ["Güçlü nakit akışı ve sağlam bilanço", "Yüksek müşteri memnuniyeti (NPS >60)", "Deneyimli ve bağlı ekip"],
    weaknesses:    ["Yüksek müşteri edinme maliyeti", "Teknik borç birikimi", "Tek ürün bağımlılığı"],
    opportunities: ["Yeni pazar segmentleri açılıyor", "AI entegrasyonu ile verimlilik artışı", "Uluslararası genişleme fırsatı"],
    threats:       ["Artan rekabet ve fiyat baskısı", "Makroekonomik belirsizlik", "Siber güvenlik riskleri"],
    strategic_priorities: ["Müşteri edinme maliyetini %20 azalt", "Teknik borca yönelik sprint planı oluştur", "APAC pazar araştırması başlat"],
  };

  const display = swot ?? ((!jobId && !orgId) ? SAMPLE : null);

  return (
    <div className={cn("space-y-4", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-sm">SWOT Analizi</h3>
          {!display && !loading && (
            <p className="text-xs text-muted-foreground">CEO pipeline'dan otomatik oluşturulur</p>
          )}
        </div>
        {(jobId || orgId) && (
          <Button
            size="sm"
            variant="outline"
            onClick={fetchSwot}
            disabled={loading}
            className="h-7 px-2 text-[11px]"
          >
            <RefreshCw className={cn("h-3 w-3 mr-1", loading && "animate-spin")} />
            {swot ? "Yenile" : "SWOT Yükle"}
          </Button>
        )}
      </div>

      {/* Error */}
      {error && (
        <p className="text-xs text-red-400 border border-red-500/20 bg-red-500/5 rounded px-2 py-1">
          {error}
        </p>
      )}

      {/* Loading skeleton */}
      {loading && !display && (
        <div className="grid grid-cols-2 gap-3 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-lg border border-border p-3 space-y-2">
              <div className="h-3 w-24 rounded bg-muted" />
              <div className="h-2 w-full rounded bg-muted" />
              <div className="h-2 w-4/5 rounded bg-muted" />
              <div className="h-2 w-3/5 rounded bg-muted" />
            </div>
          ))}
        </div>
      )}

      {/* SWOT grid */}
      {display && (
        <>
          <div className="grid grid-cols-2 gap-3">
            {QUADRANTS.map((q) => (
              <SWOTQuadrant
                key={q.key}
                quadrant={q}
                items={display[q.key] ?? []}
              />
            ))}
          </div>

          {/* Strategic priorities */}
          {display.strategic_priorities && display.strategic_priorities.length > 0 && (
            <StrategicPriorities priorities={display.strategic_priorities} />
          )}

          {/* Summary */}
          {display.summary && (
            <p className="text-xs text-muted-foreground border-t border-border pt-3 leading-relaxed">
              {display.summary}
            </p>
          )}
        </>
      )}

      {/* No data + no job */}
      {!display && !loading && !jobId && !orgId && (
        <div className="rounded-lg border border-border p-6 text-center space-y-1">
          <p className="text-sm font-medium">SWOT verisi yok</p>
          <p className="text-xs text-muted-foreground">CEO analizi çalıştırınca otomatik oluşur</p>
        </div>
      )}
    </div>
  );
}
