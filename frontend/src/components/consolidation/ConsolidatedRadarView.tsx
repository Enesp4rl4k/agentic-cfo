"use client";

import { useState } from "react";
import { Building2, Layers, ShieldCheck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import type { ConsolidatedCashRadar } from "@/lib/api/consolidation";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;

export function ConsolidatedRadarView({
  radar,
  copy,
  fmt,
}: {
  radar: ConsolidatedCashRadar;
  copy: Copy;
  fmt: Fmt;
}) {
  const [showEliminations, setShowEliminations] = useState(false);

  return (
    <div className="space-y-4">
      {/* Header Metric Cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">{copy.grpStartingCash}</span>
          </div>
          <p className="mt-1 text-lg font-bold tabular-nums">
            {fmt(radar.total_starting_cash_cents / 100)}
          </p>
        </Card>

        <Card className="border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">{copy.grpEliminatedTotal}</span>
          </div>
          <p className="mt-1 text-lg font-bold tabular-nums text-emerald-500">
            {fmt(radar.total_eliminated_cents / 100)}
          </p>
        </Card>

        <Card className="border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">{copy.grpCompanyCount}</span>
          </div>
          <p className="mt-1 text-lg font-bold tabular-nums">
            {radar.participating_org_ids.length}
          </p>
        </Card>
      </div>

      {/* Insights */}
      {radar.insights.length > 0 && (
        <Card className="border-primary/30 bg-muted/30 p-3 sm:p-4">
          <ul className="list-inside list-disc space-y-1 text-xs text-foreground">
            {radar.insights.map((ins, idx) => (
              <li key={idx}>{ins}</li>
            ))}
          </ul>
        </Card>
      )}

      {/* Consolidated 13-Week Table */}
      <Card className="overflow-x-auto p-0">
        <div className="flex items-center justify-between border-b border-border p-4">
          <div>
            <h3 className="text-sm font-semibold">{copy.grpTitle}</h3>
            <p className="text-xs text-muted-foreground">{copy.grpSubtitle}</p>
          </div>
          {radar.eliminations.length > 0 && (
            <button
              type="button"
              onClick={() => setShowEliminations(!showEliminations)}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-accent"
            >
              {showEliminations ? copy.simHide : copy.grpEliminationsTitle} ({radar.eliminations.length})
            </button>
          )}
        </div>

        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="px-3 py-2 font-medium">{copy.colWeek}</th>
              <th className="px-3 py-2 font-medium">{copy.colDates}</th>
              <th className="px-3 py-2 text-right font-medium">{copy.grpGrossIn}</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">{copy.grpEliminated}</th>
              <th className="px-3 py-2 text-right font-medium text-emerald-600 dark:text-emerald-400">{copy.grpNetIn}</th>
              <th className="px-3 py-2 text-right font-medium">{copy.grpGrossOut}</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">{copy.grpEliminated}</th>
              <th className="px-3 py-2 text-right font-medium text-destructive">{copy.grpNetOut}</th>
              <th className="px-3 py-2 text-right font-medium">{copy.colBalance}</th>
            </tr>
          </thead>
          <tbody>
            {radar.weeks.map((w) => (
              <tr key={w.week} className="border-b border-border/40 hover:bg-muted/30">
                <td className="px-3 py-2 tabular-nums">{w.week}. {copy.simWeekSuffix}</td>
                <td className="px-3 py-2 text-muted-foreground tabular-nums">{w.start_date} – {w.end_date}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{fmt(w.gross_inflow_cents / 100)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                  {w.eliminated_inflow_cents > 0 ? `-${fmt(w.eliminated_inflow_cents / 100)}` : "–"}
                </td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                  {fmt(w.net_inflow_cents / 100)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{fmt(w.gross_outflow_cents / 100)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                  {w.eliminated_outflow_cents > 0 ? `-${fmt(w.eliminated_outflow_cents / 100)}` : "–"}
                </td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-destructive">
                  {fmt(w.net_outflow_cents / 100)}
                </td>
                <td className="px-3 py-2 text-right font-bold tabular-nums">
                  {fmt(w.consolidated_balance_cents / 100)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Eliminations Drawer / Table */}
      {showEliminations && radar.eliminations.length > 0 && (
        <Card className="space-y-2 border-emerald-500/30 bg-emerald-500/5 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
            {copy.grpEliminationsTitle}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/50 text-left text-muted-foreground">
                  <th className="py-1.5 font-medium">{copy.colWeek}</th>
                  <th className="py-1.5 font-medium">{copy.grpColCompany}</th>
                  <th className="py-1.5 font-medium">{copy.grpColParty}</th>
                  <th className="py-1.5 font-medium">{copy.grpReason}</th>
                  <th className="py-1.5 text-right font-medium">{copy.grpColAmount}</th>
                </tr>
              </thead>
              <tbody>
                {radar.eliminations.map((el, i) => (
                  <tr key={i} className="border-b border-border/30">
                    <td className="py-1.5 tabular-nums">{el.week}. {copy.simWeekSuffix}</td>
                    <td className="py-1.5 font-medium">{el.org_name}</td>
                    <td className="py-1.5">{el.counterparty}</td>
                    <td className="py-1.5 text-muted-foreground">{el.eliminated_reason}</td>
                    <td className="py-1.5 text-right font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                      {fmt(el.amount_cents / 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
