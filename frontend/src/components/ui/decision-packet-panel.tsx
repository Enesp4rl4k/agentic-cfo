"use client";

/**
 * DecisionPacketPanel — the four questions asked before anyone signs, on
 * one screen: what happened, which options and what each costs, how fresh
 * the data is, and what this organisation decided the last time.
 *
 * The panel is deliberately *optional furniture*: if the packet cannot be
 * loaded it renders nothing, so the approval flow below it is never held
 * hostage by a read-only convenience endpoint.
 */
import { useEffect, useState } from "react";
import { CheckCircle2, Clock, History, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getDecisionPacket,
  type Calibration,
  type DecisionPacket,
  type FreshnessItem,
  type FreshnessState,
  type PacketOption,
} from "@/lib/api/decisionPacket";
import {
  createDecision,
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

/** Report money is kuruş — the UI shows lira. */
function fmtTL(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return tl.format(value / 100);
}

function fmtAge(item: FreshnessItem): string {
  if (item.state === "never") return "hiç senkron yok";
  if (item.age_days === null) return "yaş bilinmiyor";
  if (item.age_days === 0) return "bugün";
  return `${item.age_days} gün önce`;
}

const STATUS_CHIP = {
  open: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  closed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
} as const;

const STATUS_LABEL = { open: "açık", closed: "ölçüldü" } as const;

const STATE_CHIP: Record<FreshnessState, string> = {
  fresh: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
  aging: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  stale: "border-red-500/30 bg-red-500/10 text-red-400",
  never: "border-border bg-muted/40 text-muted-foreground",
  unknown: "border-border bg-muted/40 text-muted-foreground",
};

const RISK_BADGE: Record<string, string> = {
  low: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  high: "border-orange-500/30 bg-orange-500/10 text-orange-400",
  critical: "border-red-500/30 bg-red-500/10 text-red-400",
};

const RISK_LABEL: Record<string, string> = {
  low: "düşük",
  medium: "orta",
  high: "yüksek",
  critical: "kritik",
};

// ── Pieces ────────────────────────────────────────────────────────────────────

function FreshnessStrip({ items }: { items: FreshnessItem[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label="Veri tazeliği">
      <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
        Veri ne taze?
      </h4>
      <div className="flex flex-wrap gap-1.5">
        {items.map((f) => (
          <span
            key={f.source}
            title={f.detail ?? undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]",
              STATE_CHIP[f.state]
            )}
          >
            <span className="font-medium">{f.label}</span>
            <span className="opacity-70">{fmtAge(f)}</span>
          </span>
        ))}
      </div>
    </section>
  );
}

/** P3 — "did your forecasts actually hold?". Honest about thin data:
 *  below three closed windows it reports that, never a metric on noise. */
function CalibrationLine({ cal }: { cal?: Calibration }) {
  if (!cal) return null;
  const ok = cal.status === "ok";
  return (
    <section aria-label="Tahmin isabeti">
      <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
        Tahminler tuttu mu?
      </h4>
      {ok ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">{cal.pairs} çift</span>
          <span title="Ortalama mutlak hata (12 aylık net, kuruş)">
            ortalama hata {fmtTL(cal.mae_kurus)}
          </span>
          <span title="Ortalama simetrik yüzde hata">
            sMAPE %{cal.smape_pct ?? "—"}
          </span>
          <span title="Gerçekleşenin tahmin bandına düşme oranı">
            bant kapsama %{cal.coverage_pct ?? "—"}
          </span>
          <span title="Pozitif = tahmin gerçekleşenden iyimser">
            sapma {cal.bias_kurus != null && cal.bias_kurus > 0 ? "+" : ""}
            {fmtTL(cal.bias_kurus)}
          </span>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Yeterli veri yok — {cal.pairs} kapanmış tahmin penceresi (en az 3 gerekir).
        </p>
      )}
    </section>
  );
}

function SituationRow({ packet }: { packet: DecisionPacket }) {
  const s = packet.situation;
  const cells: { label: string; value: string }[] = [
    { label: "12 ay gelir", value: fmtTL(s.revenue_12m) },
    { label: "Nakit ömrü (baz)", value: s.runway_months != null ? `${s.runway_months} ay` : "—" },
    {
      label: "En büyük gider",
      value: s.top_opex_category ? `${s.top_opex_category} · ${fmtTL(s.top_opex_amount)}` : "—",
    },
    { label: "Anomali", value: `${s.anomaly_count}` },
  ];
  return (
    <section aria-label="Durum">
      <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">Ne oldu?</h4>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        {cells.map((c) => (
          <div key={c.label}>
            <dt className="text-[11px] text-muted-foreground">{c.label}</dt>
            <dd className="text-sm font-medium">{c.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function OptionsTable({ options }: { options: PacketOption[] }) {
  if (options.length === 0) return null;
  return (
    <section aria-label="Seçenekler">
      <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
        Hangi seçenekler, sonuçları ne?
      </h4>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/30 text-left text-xs text-muted-foreground">
              <th className="px-3 py-2 font-medium">Seçenek</th>
              <th className="px-3 py-2 text-right font-medium">12 ay net etki</th>
              <th className="px-3 py-2 text-right font-medium">Break-even</th>
              <th className="px-3 py-2 text-right font-medium">Nakit riski</th>
            </tr>
          </thead>
          <tbody>
            {options.map((o) => (
              <tr
                key={o.id}
                className={cn(
                  "border-b last:border-b-0",
                  o.baseline && "bg-muted/20 font-medium"
                )}
              >
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5">
                    {o.label}
                    {o.baseline && (
                      <Badge variant="outline" className="text-[10px]">
                        referans
                      </Badge>
                    )}
                  </span>
                  {o.assumptions.length > 0 && (
                    <span className="mt-0.5 block text-[11px] font-normal leading-snug text-muted-foreground">
                      {o.assumptions.join(" · ")}
                    </span>
                  )}
                </td>
                <td
                  className={cn(
                    "px-3 py-2 text-right tabular-nums",
                    !o.baseline &&
                      (o.base_net_impact >= 0 ? "text-emerald-500" : "text-red-400")
                  )}
                >
                  {o.baseline ? "0 ₺ (referans)" : fmtTL(o.base_net_impact)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {o.breakeven_months != null ? `${o.breakeven_months} ay` : "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  {o.cashflow_risk ? (
                    <span
                      className={cn(
                        "inline-block rounded-full border px-2 py-0.5 text-[11px]",
                        RISK_BADGE[o.cashflow_risk] ?? "border-border text-muted-foreground"
                      )}
                    >
                      {RISK_LABEL[o.cashflow_risk] ?? o.cashflow_risk}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Varsayımları kendiniz değiştirip denemek için{" "}
        <a href="/simulation?tab=counterfactual" className="underline underline-offset-2">
          simülasyonu açın
        </a>
        .
      </p>
    </section>
  );
}

function PrecedentSection({ packet }: { packet: DecisionPacket }) {
  const { decisions, pending_actions } = packet.precedent;
  return (
    <section aria-label="Geçmiş kararlar">
      <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <History className="h-3.5 w-3.5" aria-hidden="true" />
        Geçmişte ne oldu?
        {pending_actions > 0 && (
          <Badge variant="outline" className="ml-auto text-[10px]">
            {pending_actions} açık aksiyon
          </Badge>
        )}
      </h4>
      {decisions.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Bu organizasyon için kayıtlı karar bulunmuyor.
        </p>
      ) : (
        <ul className="space-y-1">
          {decisions.map((d) => (
            <li key={d.id} className="rounded-md border px-2.5 py-1.5 text-[11px]">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium">{d.topic}</span>
                <span className="text-muted-foreground">
                  {d.created_at.slice(0, 10)} · {d.resolution_status}
                </span>
              </span>
              <span className="mt-0.5 block text-muted-foreground">{d.final_decision}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Decision recorder ─────────────────────────────────────────────────────────

/**
 * Write the decision into the ledger right where it is made. `expected` is
 * filled server-side from this packet — the manager picks an option and
 * writes a why, never the numbers they claim to have expected. An already
 * recorded decision for this job replaces the form: one decision per
 * review moment is the backend's rule, not a UI preference.
 */
function DecisionRecorder({
  jobId,
  options,
}: {
  jobId: string;
  options: PacketOption[];
}) {
  const [loading, setLoading] = useState(true);
  const [decision, setDecision] = useState<DecisionRecord | null>(null);
  const [optionId, setOptionId] = useState("");
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [measuring, setMeasuring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDecisions({ jobId, limit: 1 })
      .then((rows) => {
        if (!cancelled) setDecision(rows[0] ?? null);
      })
      .catch(() => {
        // Furniture: a failed prefill shows the form rather than blocking it.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const save = async () => {
    if (!optionId || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await createDecision({
        jobId,
        optionId,
        rationale: rationale.trim() || undefined,
      });
      setDecision(created);
    } catch {
      setError("Karar kaydedilemedi — tekrar deneyin.");
    } finally {
      setSaving(false);
    }
  };

  const measure = async () => {
    if (!decision || measuring) return;
    setMeasuring(true);
    setError(null);
    try {
      const updated = await measureOutcome(decision.id);
      setDecision(updated);
    } catch {
      setError(
        "Sonuç ölçülemedi — ölçüm için tamamlanmış bir analiz gerekiyor olabilir."
      );
    } finally {
      setMeasuring(false);
    }
  };

  if (loading) return null;

  if (decision) {
    const v = decision.variance;
    return (
      <section aria-label="Karar defteri">
        <h4 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          Karar defteri
          <Badge
            variant="outline"
            className={cn("ml-auto text-[10px]", STATUS_CHIP[decision.status])}
          >
            {STATUS_LABEL[decision.status]}
          </Badge>
        </h4>
        <div className="rounded-md border px-2.5 py-1.5 text-[11px]">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">{decision.topic}</span>
            <span className="text-muted-foreground">
              {decision.created_at.slice(0, 10)}
            </span>
          </span>
          <span className="mt-0.5 block text-muted-foreground">
            Seçilen: {decision.chosen_option_label}
            {decision.rationale ? ` · ${decision.rationale}` : ""}
          </span>
          {decision.status === "closed" && v && (
            <span className="mt-1 flex flex-wrap gap-x-3">
              <span>
                Karardan bu yana net:{" "}
                <span
                  className={cn(
                    "font-medium tabular-nums",
                    v.realized_net_kurus >= 0 ? "text-emerald-500" : "text-red-400"
                  )}
                >
                  {fmtTL(v.realized_net_kurus)}
                </span>
              </span>
              {v.runway_delta !== undefined && (
                <span>
                  Pist:{" "}
                  <span
                    className={cn(
                      "font-medium tabular-nums",
                      v.runway_delta >= 0 ? "text-emerald-500" : "text-red-400"
                    )}
                  >
                    {v.runway_delta > 0 ? "+" : ""}
                    {v.runway_delta} ay
                  </span>
                </span>
              )}
            </span>
          )}
          {decision.status === "open" && (
            <button
              type="button"
              onClick={measure}
              disabled={measuring}
              className="mt-1.5 rounded-md border px-2 py-0.5 text-[11px] hover:bg-muted/40 disabled:opacity-50"
            >
              {measuring ? "Ölçülüyor…" : "Sonucu ölç"}
            </button>
          )}
          {error && <p className="mt-1 text-red-400">{error}</p>}
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Kararı deftere yaz">
      <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
        Kararı deftere yaz
      </h4>
      <div className="space-y-1.5 rounded-md border p-2.5">
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Karar seçeneği"
            value={optionId}
            onChange={(e) => setOptionId(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="">Seçenek seçin…</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={save}
            disabled={!optionId || saving}
            className="h-8 rounded-md border px-2.5 text-xs font-medium hover:bg-muted/40 disabled:opacity-50"
          >
            {saving ? "Kaydediliyor…" : "Kararı deftere yaz"}
          </button>
        </div>
        <textarea
          aria-label="Gerekçe"
          rows={2}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Gerekçe (isteğe bağlı) — bu karar neden alındı?"
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Beklenti, paketin kendi rakamlarıyla sunucuda sabitlenir — sonradan
          değiştirilemez.
        </p>
        {error && <p className="text-[11px] text-red-400">{error}</p>}
      </div>
    </section>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function DecisionPacketPanel({
  jobId,
  className,
}: {
  jobId: string;
  className?: string;
}) {
  const [packet, setPacket] = useState<DecisionPacket | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getDecisionPacket(jobId)
      .then((p) => {
        if (!cancelled) setPacket(p ?? null);
      })
      .catch(() => {
        // The packet is a read-only convenience — a failure renders nothing
        // and never blocks the approval flow underneath it.
        if (!cancelled) setPacket(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (loading) return <Skeleton className={cn("h-24 w-full", className)} />;
  if (!packet) return null;

  return (
    <Card className={cn("border-border/60", className)}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5 text-sm">
          <Scale className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Karar Paketi
          {packet.gate.reason && (
            <span className="ml-auto font-normal text-[11px] text-amber-500">
              {packet.gate.reason}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <SituationRow packet={packet} />
        <FreshnessStrip items={packet.freshness} />
        <CalibrationLine cal={packet.calibration} />
        <OptionsTable options={packet.options} />
        {packet.options.length > 0 && (
          <DecisionRecorder jobId={jobId} options={packet.options} />
        )}
        <PrecedentSection packet={packet} />
        {packet.evidence.trim() && (
          <details className="text-[11px] text-muted-foreground">
            <summary className="cursor-pointer select-none">Kanıt parçaları</summary>
            <pre className="mt-1.5 whitespace-pre-wrap rounded-md bg-muted/30 p-2 font-mono text-[10px]">
              {packet.evidence}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
