"use client";

import { useState } from "react";
import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { badgeVariants } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { RadarItem, RadarWeek } from "@/lib/api/ledger";

// How a radar figure is known (backend app/services/cash_radar.py): `known` comes from a
// document with a due date, `estimated` from history, `assumed` from a placement rule. The page
// never recomputes any of it; it shows the basis the server sent, quietly, beside the figure.

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;
type Split = RadarWeek["inflow_basis"];

/** "12 Kasım": the day a statement closes, in the organisation's language. */
export function formatDay(iso: string, locale: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString(locale, {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });
}

const num = (inputs: RadarItem["basis_inputs"], key: string): number => Number(inputs?.[key] ?? 0);
const text = (inputs: RadarItem["basis_inputs"], key: string, locale: string): string =>
  formatDay(String(inputs?.[key] ?? ""), locale);

function reasonText(item: RadarItem, copy: Copy, fmt: Fmt, locale: string): string {
  const inputs = item.basis_inputs;
  switch (item.basis_reason) {
    case "recurring_median":
      return copy.reasonRecurring
        .replace("{months}", String(num(inputs, "months_observed")))
        .replace("{median}", fmt(num(inputs, "median_cents") / 100))
        .replace("{day}", String(num(inputs, "day_of_month")));
    case "tax_historical_median":
      return (
        copy.reasonTax
          .replace("{count}", String(num(inputs, "payments_observed")))
          .replace("{median}", fmt(num(inputs, "median_cents") / 100)) +
        (item.rules_verified === false ? copy.reasonTaxUnverified : "")
      );
    case "customer_average_delay":
      return copy.reasonDelay.replace("{days}", String(num(inputs, "average_delay_days")));
    case "overdue_payable_placed_in_week_1":
      return copy.reasonOverdue.replace("{due}", text(inputs, "due_date", locale));
    case "payment_plan_change_taken_as_date":
      return copy.reasonPlan
        .replace("{planned}", text(inputs, "planned_date", locale))
        .replace("{due}", text(inputs, "document_due_date", locale));
    default:
      return copy.reasonFallback;
  }
}

/** A small "tahmini" / "varsayım" tag with the reason on hover, focus or tap. Documented rows get none. */
export function BasisTag({ item, copy, fmt, locale }: Readonly<{ item: RadarItem; copy: Copy; fmt: Fmt; locale: string }>) {
  const [open, setOpen] = useState(false);
  if (item.basis === "known") return null;
  const reason = reasonText(item, copy, fmt, locale);
  const label = item.basis === "assumed" ? copy.tagAssumed : copy.tagEstimated;
  return (
    <>
      <button
        type="button"
        title={reason}
        aria-expanded={open}
        aria-label={copy.tagReasonLabel.replace("{reason}", reason)}
        onClick={() => setOpen((v) => !v)}
        className={cn(badgeVariants({ variant: "outline" }), "ml-1.5 px-1.5 py-0 align-middle text-[11px] font-normal text-muted-foreground")}
      >
        {label}
      </button>
      {open && <span className="mt-0.5 block text-xs text-muted-foreground">{reason}</span>}
    </>
  );
}

export function hasUnverifiedTax(items: RadarItem[]): boolean {
  return items.some((item) => item.instrument === "tax" && item.rules_verified === false);
}

/** Said wherever a tax row appears: its day rules are not checked against the official text. */
export function TaxRulesNote({ copy }: Readonly<{ copy: Copy }>) {
  return <p className="m-0 text-xs text-muted-foreground">{copy.taxUnverifiedNote}</p>;
}

/** How much of one side of a week is documented, estimated or assumed; nothing is said when all is documented. */
export function BasisSplitLine({ split, copy, fmt }: Readonly<{ split: Split; copy: Copy; fmt: Fmt }>) {
  if (split.estimated_cents + split.assumed_cents === 0) return null;
  const parts: [string, number][] = [
    [copy.basisKnown, split.known_cents],
    [copy.basisEstimated, split.estimated_cents],
    [copy.basisAssumed, split.assumed_cents],
  ];
  return (
    <span className="block text-[11px] font-normal text-muted-foreground">
      {parts
        .filter(([, cents]) => cents > 0)
        .map(([label, cents]) => `${label} ${fmt(cents / 100)}`)
        .join(" · ")}
    </span>
  );
}

/** The warning over a balance older than the server's threshold, with the way to a newer statement. */
export function StaleBalanceNotice({ asOf, ageDays, locale }: Readonly<{ asOf: string; ageDays: number; locale: string }>) {
  const { t } = useI18n();
  const copy = t.cashRadar;
  return (
    <Alert variant="warning">
      <AlertTitle>{copy.staleTitle.replace("{days}", String(ageDays))}</AlertTitle>
      <AlertDescription>
        {copy.staleBody.replace("{date}", formatDay(asOf, locale))}{" "}
        <Link href="/baglan" className="inline-flex min-h-[44px] items-center font-medium text-primary underline-offset-4 hover:underline">
          {copy.staleUpload}
        </Link>
      </AlertDescription>
    </Alert>
  );
}
