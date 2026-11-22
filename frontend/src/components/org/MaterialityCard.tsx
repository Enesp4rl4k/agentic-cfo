"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCentsFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { acknowledgeMateriality, getMateriality, setMateriality, type Materiality } from "@/lib/api/scale";

const KEY = ["materiality"] as const;

/**
 * The amount above which a decision needs the owner or an admin, as a share of the company's own
 * monthly outflow, with its basis written out. The system proposes; nothing applies until a person
 * confirms ("Öneriyi onayla ve uygula") or sets their own amount, and both are recorded. Until then the
 * fixed amount that always applied still applies, and the card says so. Owner and admin only: for
 * anyone else the server answers without a proposal and the card renders nothing.
 */
export function MaterialityCard() {
  const { t } = useI18n();
  const m = t.scale.materiality;
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: KEY, queryFn: getMateriality, retry: false });
  const cents = useCentsFormat(data?.current.currency);
  const [own, setOwn] = useState(false);
  const [lira, setLira] = useState("");
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<"saved" | "stale" | "error" | null>(null);

  if (!data || !data.can_decide) return null;
  const { current, proposal } = data;

  async function run(action: () => Promise<Materiality>) {
    setNotice(null);
    try {
      qc.setQueryData(KEY, await action());
      setOwn(false);
      setLira("");
      setReason("");
      setNotice("saved");
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setNotice(status === 409 ? "stale" : "error");
      if (status === 409) await qc.invalidateQueries({ queryKey: KEY });
    }
  }

  const amount = Math.round(Number(lira.replace(",", ".")) * 100);
  const ownValid = Number.isFinite(amount) && amount > 0;

  return (
    <Card className="space-y-3 p-4">
      <h2 className="tc-display m-0 text-[20px]">{m.title}</h2>
      <p className="m-0 text-sm text-muted-foreground">{m.intro}</p>
      <div className="space-y-1">
        <p className="m-0 text-sm font-medium">{m.current.replace("{amount}", cents(current.threshold_cents))}</p>
        <p className="m-0 text-xs text-muted-foreground">
          {current.acknowledged ? m.basis.replace("{basis}", current.basis_text) : m.fixedNote}
        </p>
      </div>

      {proposal && proposal.differs_from_current && !own && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <p className="m-0 text-sm font-medium">{m.proposalTitle.replace("{amount}", cents(proposal.amount_cents))}</p>
          <p className="m-0 text-xs text-muted-foreground">{m.basis.replace("{basis}", proposal.basis_text)}</p>
          <p className="m-0 text-xs text-muted-foreground">{m.proposalHint}</p>
          <div className="flex flex-wrap gap-2">
            <Button className="min-h-[44px]" onClick={() => void run(() => acknowledgeMateriality(proposal.amount_cents))}>
              {m.acknowledge}
            </Button>
            <Button variant="outline" className="min-h-[44px]" onClick={() => setOwn(true)}>
              {m.own}
            </Button>
          </div>
        </div>
      )}

      {(own || !proposal || !proposal.differs_from_current) && (
        <div className="space-y-2">
          {!own ? (
            <Button variant="outline" className="min-h-[44px]" onClick={() => setOwn(true)}>
              {m.own}
            </Button>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-sm">
                {m.ownLabel}
                <input
                  inputMode="decimal"
                  value={lira}
                  onChange={(e) => setLira(e.target.value)}
                  className="min-h-[44px] w-40 rounded-md border border-border bg-card px-3 text-sm"
                />
              </label>
              <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm">
                {m.reasonLabel}
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="min-h-[44px] rounded-md border border-border bg-card px-3 text-sm"
                />
              </label>
              <Button className="min-h-[44px]" disabled={!ownValid} onClick={() => void run(() => setMateriality(amount, reason))}>
                {m.save}
              </Button>
              <Button variant="outline" className="min-h-[44px]" onClick={() => setOwn(false)}>
                {m.cancel}
              </Button>
            </div>
          )}
        </div>
      )}

      {notice === "saved" && <p role="status" className="m-0 text-sm text-success">{m.saved}</p>}
      {notice === "stale" && <p role="alert" className="m-0 text-sm text-destructive">{m.stale}</p>}
      {notice === "error" && <p role="alert" className="m-0 text-sm text-destructive">{m.error}</p>}
      <p className="m-0 text-xs text-muted-foreground">{m.safety}</p>
    </Card>
  );
}
