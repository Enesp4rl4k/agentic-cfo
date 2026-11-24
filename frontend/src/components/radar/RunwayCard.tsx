"use client";

import Link from "next/link";

import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { cn } from "@/lib/utils";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];

/**
 * The measured runway, as the server worded it (backend app/services/runway.py: the forecast's own
 * computation, read by the radar and the Monday briefing). The page computes nothing: a number is
 * shown only when the server measured one, an assumption is badged where the number is, and an
 * unknown balance reads "unknown" with no figure beside it.
 */
export function RunwayCard({
  status,
  level,
  basis,
  months,
  text,
  copy,
  locale,
  attention = false,
  cashGone = false,
  uploadHref = null,
}: Readonly<{
  status: string;
  level: string | null;
  /** Low (at or below the server's attention months), known or assumed: styled apart from neutral cards. */
  attention?: boolean;
  /** The balance is already at or below zero (server flag): said as that, never as "under a month". */
  cashGone?: boolean;
  /** Where a new statement is uploaded, shown when the figure rests on an old statement. */
  uploadHref?: string | null;
  basis: string | null;
  months: number | null;
  text: string;
  copy: Copy;
  locale: string;
}>) {
  const critical = level === "critical";
  const attend = attention && !critical;
  const measured = status === "computed" || status === "not_burning";
  let value: string | null = null;
  if (months !== null) {
    value = cashGone
      ? (basis === "assumed" ? copy.runwayCashGoneAssumed : copy.runwayCashGone)
      : months < 1
      ? copy.runwayUnderMonth
      : copy.runwayMonths.replace("{n}", months.toLocaleString(locale, { maximumFractionDigits: 1 }));
  } else if (!measured) {
    value = copy.runwayUnknown;
  }
  return (
    <Card
      className={cn("space-y-2 p-4", critical && "border-destructive", attend && "border-2 border-amber-500")}
      role={critical || attend ? "alert" : "status"}
      data-attention={attention ? "true" : undefined}
      data-testid="runway-card"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="tc-display m-0 text-[20px] leading-tight">{copy.runwayTitle}</h2>
        {value !== null && (
          <span className={cn("tc-mono text-[22px]", critical && "text-destructive")} data-testid="runway-value">
            {value}
          </span>
        )}
        {critical && <span className="text-xs font-semibold uppercase text-destructive">{copy.runwayCritical}</span>}
        {attend && <span className="text-xs font-semibold uppercase" data-testid="runway-attention">{copy.runwayAttention}</span>}
        {level === "warning" && !attend && <span className="text-xs font-semibold uppercase">{copy.runwayWarning}</span>}
        {basis === "assumed" && (
          <span className="rounded-full border border-border px-2 py-0.5 text-xs" data-testid="runway-assumed">
            {copy.runwayAssumed}
          </span>
        )}
      </div>
      {basis === "assumed" && <p className="m-0 text-xs text-muted-foreground">{copy.runwayAssumedHint}</p>}
      <p className="m-0 text-sm text-muted-foreground" data-testid="runway-text">
        {text}
      </p>
      {uploadHref && (
        <Link href={uploadHref} className="text-sm underline" data-testid="runway-upload">
          {copy.runwayUploadLink}
        </Link>
      )}
    </Card>
  );
}
