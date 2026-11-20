"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import type { RadarItem, RadarWeek } from "@/lib/api/ledger";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];

function Group({ label, items, copy, fmt }: { label: string; items: RadarItem[]; copy: Copy; fmt: (v: number) => string }) {
  if (items.length === 0) return null;
  const total = items.reduce((sum, item) => sum + item.amount_cents, 0);
  return (
    <div className="flex flex-col text-[13.5px]">
      <span className="pb-1 text-xs text-muted-foreground">
        {label} · <span className="tc-mono">{fmt(total / 100)}</span>
      </span>
      <ul>
        {[...items]
          .sort((a, b) => b.amount_cents - a.amount_cents)
          .map((item) => (
            <li key={item.id} className="flex justify-between gap-3 border-t border-border py-1.5">
              <span>
                {item.counterparty || item.description || copy.weekDetailItem}
                {item.is_overdue && <span className="text-muted-foreground"> · {copy.weekDetailLate}</span>}
              </span>
              <span className="tc-mono shrink-0">{fmt(item.amount_cents / 100)}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}

/** What the chosen week is made of, item by item, with the way to the source documents. */
export function WeekDetail({ week, copy, fmt }: { week: RadarWeek; copy: Copy; fmt: (v: number) => string }) {
  const empty = week.payables.length === 0 && week.receivables.length === 0;
  return (
    <section
      aria-label={copy.weekDetailTitle}
      className="flex flex-col gap-3 self-start rounded-xl border-[1.5px] bg-card p-5"
      style={{ borderColor: "var(--tc-ember)" }}
    >
      <span className="tc-eyebrow font-semibold" style={{ color: "var(--tc-ember-text)" }}>
        {copy.weekDetailEyebrow
          .replace("{week}", String(week.week))
          .replace("{start}", week.start_date)
          .replace("{end}", week.end_date)}
      </span>
      <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{copy.weekDetailTitle}</h2>
      {empty ? (
        <p className="text-sm text-muted-foreground">{copy.weekDetailEmpty}</p>
      ) : (
        <>
          <Group label={copy.weekDetailPayments} items={week.payables} copy={copy} fmt={fmt} />
          <Group label={copy.weekDetailCollections} items={week.receivables} copy={copy} fmt={fmt} />
        </>
      )}
      <Link href="/baglan" className="inline-flex min-h-[44px] items-center text-sm font-medium underline-offset-4 hover:underline" style={{ color: "var(--tc-ember-text)" }}>
        {copy.openSources}
      </Link>
    </section>
  );
}
