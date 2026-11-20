"use client";

import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import {
  deleteOgrenilmisKural,
  getOgrenilmisKurallar,
  type OgrenilmisKural,
} from "@/lib/api/smmm";

/**
 * What the agent learned from this company's accountant, and a way to take it back.
 *
 * A rule is made by two consistent single corrections and only *suggests* the
 * account: the entry still waits for the accountant. This list says what was
 * learned, how many corrections stand behind it and whether it is in force, and
 * lets a wrong one be removed instead of waiting for two contrary corrections.
 */
export function OgrenilmisKurallar() {
  const { t } = useI18n();
  const k = t.learnedRules;
  const [rows, setRows] = useState<OgrenilmisKural[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await getOgrenilmisKurallar());
      setError(null);
    } catch {
      setError(k.loadError);
    }
  }, [k.loadError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(row: OgrenilmisKural) {
    if (!confirm(k.confirm)) return;
    setBusy(row.id);
    setError(null);
    try {
      await deleteOgrenilmisKural(row.id);
      setRows((prev) => (prev ?? []).filter((r) => r.id !== row.id));
    } catch (e) {
      // A role that may not decide is told why (403); anything else gets our wording.
      const status = (e as Error & { status?: number }).status;
      setError(status === 403 && e instanceof Error && e.message ? e.message : k.deleteError);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3" aria-labelledby="ogrenilmis-kurallar-baslik">
      <div>
        <h2 id="ogrenilmis-kurallar-baslik" className="text-base font-semibold">
          {k.title}
        </h2>
        <p className="text-xs text-muted-foreground">{k.subtitle}</p>
      </div>

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}

      {rows !== null && rows.length === 0 && !error && (
        <Card className="p-4 text-sm text-muted-foreground">{k.empty}</Card>
      )}

      {rows !== null && rows.length > 0 && (
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li key={row.id}>
              <Card className="flex items-center gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{row.anahtar}</p>
                  <p className="text-xs text-muted-foreground">
                    <span className="font-mono">{row.hesap_kodu}</span>
                    {row.hesap_adi ? ` · ${row.hesap_adi}` : ""}
                    {" · "}
                    {k.times.replace("{count}", String(row.onay_sayisi))}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded px-1.5 py-0.5 text-[11px]",
                    row.aktif
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {row.aktif ? k.inForce : k.notYet}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(row)}
                  disabled={busy === row.id}
                  className="shrink-0 rounded p-1.5 text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                  title={k.delete}
                  aria-label={k.deleteAria.replace("{name}", row.anahtar)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
