"use client";

import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useI18n } from "@/hooks/useI18n";
import { getSmmmTakvim, type SmmmTakvim as Takvim } from "@/lib/api/smmm";

/**
 * Every client's upcoming statutory deadlines, nearest first.
 *
 * Dates come from day rules not yet checked against GİB/SGK's own text, and the
 * page says so whenever the server does. An amount is shown only when that client
 * has paid that tax from its bank before; otherwise the cell says there is no
 * history rather than showing an estimate.
 */
export function SmmmTakvim() {
  const { t, locale } = useI18n();
  const c = t.smmmCalendar;
  const [data, setData] = useState<Takvim | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    getSmmmTakvim(45)
      .then((d) => alive && setData(d))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, []);

  const tag = locale === "tr" ? "tr-TR" : "en-US";
  const money = (kurus: number) =>
    new Intl.NumberFormat(tag, { style: "currency", currency: "TRY" }).format(kurus / 100);
  const day = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString(tag, { day: "2-digit", month: "short", weekday: "short" });

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <CalendarClock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <h2 className="text-base font-semibold">{c.title}</h2>
      </div>
      <p className="text-xs text-muted-foreground">{c.subtitle}</p>

      {data && data.kurallar_dogrulandi === false && (
        <p className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-400">
          {c.unverified}
        </p>
      )}

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {c.loadError}
        </p>
      )}

      {data && data.kalemler.length === 0 && <p className="text-sm text-muted-foreground">{c.empty}</p>}

      {data && data.kalemler.length > 0 && (
        <ul className="divide-y divide-border/60">
          {data.kalemler.map((k) => (
            <li key={`${k.musteri_id}-${k.tur}-${k.tarih}`} className="flex items-center gap-3 py-2 text-sm">
              <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">{day(k.tarih)}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{k.firma_adi}</span>
                <span className="block truncate text-xs text-muted-foreground">{k.baslik}</span>
              </span>
              <span
                className={cn(
                  "shrink-0 text-right text-xs",
                  k.tutar_kurus === null ? "text-muted-foreground" : "font-mono",
                )}
              >
                {k.tutar_kurus === null ? c.noHistory : money(k.tutar_kurus)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
