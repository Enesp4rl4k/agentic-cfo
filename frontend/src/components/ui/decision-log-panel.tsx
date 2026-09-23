"use client";

/**
 * DecisionLogPanel — the organisation's decision ledger on one screen:
 * what was decided, what was expected (server-fixed from the packet), and,
 * once measured, what actually happened after new data arrived.
 *
 * The backend refuses a second measurement; this panel simply offers the
 * button while a decision is open. Optional furniture: a failed load
 * renders the empty state, never a crashed command centre.
 */
import { useCallback, useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  listDecisions,
  measureOutcome,
  type DecisionRecord,
} from "@/lib/api/decisions";
import { cn } from "@/lib/utils";

// ── Formatting ────────────────────────────────────────────────────────────────

const tl = new Intl.NumberFormat("tr-TR", {
  style: "currency",
  currency: "TRY",
  maximumFractionDigits: 0,
});

/** Ledger money is kuruş — the UI shows lira. */
function fmtTL(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return tl.format(value / 100);
}

const STATUS_CHIP = {
  open: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  closed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
} as const;

const STATUS_LABEL = { open: "açık", closed: "ölçüldü" } as const;

// ── Panel ─────────────────────────────────────────────────────────────────────

export function DecisionLogPanel({ className }: { className?: string }) {
  const [rows, setRows] = useState<DecisionRecord[] | null>(null);
  const [measuringId, setMeasuringId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listDecisions({ limit: 50 })
      .then((data) => setRows(data))
      .catch(() => setRows([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const measure = async (id: string) => {
    setMeasuringId(id);
    setError(null);
    try {
      const updated = await measureOutcome(id);
      setRows((prev) => (prev ?? []).map((r) => (r.id === id ? updated : r)));
    } catch {
      setError(
        "Sonuç ölçülemedi — ölçüm için tamamlanmış bir analiz gerekiyor olabilir."
      );
    } finally {
      setMeasuringId(null);
    }
  };

  const openCount = (rows ?? []).filter((r) => r.status === "open").length;

  return (
    <Card
      className={cn("border-border/60", className)}
      data-testid="decision-log"
    >
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5 text-sm">
          <BookOpen className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Karar Defteri
          {rows && rows.length > 0 && (
            <span className="ml-auto flex gap-1.5 font-normal">
              <Badge variant="outline" className="text-[10px]">
                {openCount} açık
              </Badge>
              <Badge variant="outline" className="text-[10px]">
                {rows.length - openCount} ölçüldü
              </Badge>
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows === null ? (
          <Skeleton className="h-16 w-full" />
        ) : rows.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            Kayıtlı karar yok — onay bekleyen bir analizde karar paketinden bir
            kararı deftere yazabilirsiniz.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((r) => (
              <li key={r.id} className="rounded-md border px-2.5 py-1.5 text-[11px]">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium">{r.topic}</span>
                  <span className="text-muted-foreground">
                    {r.created_at.slice(0, 10)}
                  </span>
                  <Badge
                    variant="outline"
                    className={cn("ml-auto text-[10px]", STATUS_CHIP[r.status])}
                  >
                    {STATUS_LABEL[r.status]}
                  </Badge>
                </span>
                <span className="mt-0.5 block text-muted-foreground">
                  Seçilen: {r.chosen_option_label}
                  {r.rationale ? ` · ${r.rationale}` : ""}
                </span>
                {r.status === "closed" && r.variance && (
                  <span className="mt-1 flex flex-wrap gap-x-3">
                    <span>
                      Karardan bu yana net:{" "}
                      <span
                        className={cn(
                          "font-medium tabular-nums",
                          r.variance.realized_net_kurus >= 0
                            ? "text-emerald-500"
                            : "text-red-400"
                        )}
                      >
                        {fmtTL(r.variance.realized_net_kurus)}
                      </span>
                    </span>
                    {r.variance.runway_delta !== undefined && (
                      <span>
                        Pist:{" "}
                        <span
                          className={cn(
                            "font-medium tabular-nums",
                            r.variance.runway_delta >= 0
                              ? "text-emerald-500"
                              : "text-red-400"
                          )}
                        >
                          {r.variance.runway_delta > 0 ? "+" : ""}
                          {r.variance.runway_delta} ay
                        </span>
                      </span>
                    )}
                  </span>
                )}
                {r.status === "open" && (
                  <button
                    type="button"
                    onClick={() => measure(r.id)}
                    disabled={measuringId === r.id}
                    className="mt-1.5 rounded-md border px-2 py-0.5 text-[11px] hover:bg-muted/40 disabled:opacity-50"
                  >
                    {measuringId === r.id ? "Ölçülüyor…" : "Sonucu ölç"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {error && <p className="mt-1.5 text-[11px] text-red-400">{error}</p>}
      </CardContent>
    </Card>
  );
}
