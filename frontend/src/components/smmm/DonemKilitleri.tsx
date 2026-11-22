"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Lock } from "lucide-react";
import { CanButton } from "@/components/ui/can-button";
import { Card } from "@/components/ui/card";
import { useCan } from "@/hooks/useCan";
import { useI18n } from "@/hooks/useI18n";
import { failureMessage } from "@/lib/forbidden";
import { closePeriod, getClosedPeriods, type KapaliDonem } from "@/lib/api/smmm";

/** The last twelve months, newest first, as "YYYY-MM" (the current month included). */
function lastMonths(now: Date, n = 12): string[] {
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

/**
 * Closed months of the company the accountant is working in, and a way to close one.
 *
 * Closing is not undone here: once a month is closed its ledger rows stay as they are,
 * and anything that belongs to it but arrives later is booked in the first open month,
 * marked with the closed period. The control asks before it closes.
 */
export function DonemKilitleri({ now = new Date() }: { now?: Date }) {
  const { t } = useI18n();
  const p = t.periodLock;
  const can = useCan("closePeriod");
  const [closed, setClosed] = useState<KapaliDonem[] | null>(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setClosed(await getClosedPeriods());
    } catch {
      setError(p.loadError);
    }
  }, [p.loadError]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = useMemo(() => {
    const shut = new Set((closed ?? []).map((c) => c.donem));
    return lastMonths(now).filter((m) => !shut.has(m));
  }, [closed, now]);

  async function close() {
    if (!choice || !confirm(p.confirm.replace("{donem}", choice))) return;
    setBusy(true);
    setError(null);
    try {
      await closePeriod(choice);
      setChoice("");
      await load();
    } catch (e) {
      // A refusal the server explains (role, already closed, future month) is shown as given.
      const status = (e as Error & { status?: number }).status;
      setError(
        status === 403
          ? failureMessage(e, p.closeError, t.roleGate.forbidden)
          : status && status < 500 && e instanceof Error && e.message ? e.message : p.closeError,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <h2 className="text-base font-semibold">{p.title}</h2>
      </div>
      <p className="text-xs text-muted-foreground">{p.subtitle}</p>
      {can.note && <p className="text-xs">{can.note}</p>}

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}

      {closed !== null && (
        <p className="text-sm">
          {closed.length === 0 ? p.none : `${p.closedLabel}: ${closed.map((c) => c.donem).join(", ")}`}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="donem-sec" className="text-xs">
          {p.chooseLabel}
        </label>
        <select
          id="donem-sec"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="rounded-md border border-border bg-card px-2 py-1 text-xs"
        >
          <option value="">{p.choose}</option>
          {open.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <CanButton action="closePeriod" size="sm" variant="outline" disabled={!choice || busy} onClick={() => void close()}>
          {p.close}
        </CanButton>
      </div>
    </Card>
  );
}
