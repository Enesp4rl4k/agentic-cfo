"use client";

import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { formatCurrency } from "@/lib/utils";

/** One non-base currency, summed on its own (backend app/core/currency_totals.py). Kuruş. */
export interface OtherCurrency {
  currency: string;
  revenue_cents?: number;
  expense_cents?: number;
  cash_in_cents?: number;
  cash_out_cents?: number;
  rows?: number;
  assumed_rows?: number;
}

/** A currency code for display: an unknown one ("?", empty) is said to be unknown, never printed as a code. */
export const shownCode = (code: string | null | undefined, unknown: string) =>
  /^[A-Za-z]{3}$/.test((code ?? "").trim()) ? (code as string) : unknown;

/**
 * What is not in the headline figure: every other currency, as its own line.
 *
 * Amounts in different currencies are never added, and no exchange rate is kept, so
 * these are shown beside the base total and labelled "not converted". `kind` picks
 * revenue/expense (profit) or money in/out (cash).
 */
export function OtherCurrencyLines({
  items,
  base,
  kind = "profit",
  ratios = false,
}: {
  items: OtherCurrency[] | null | undefined;
  base: string;
  kind?: "profit" | "cash";
  /** Also say that margins and changes are base-currency only. */
  ratios?: boolean;
}) {
  const { t } = useI18n();
  const { org } = useOrgSettings();
  const copy = t.otherCurrency;
  const locale = org?.locale || "en-US";
  if (!items?.length) return null;

  const money = (cents: number, code: string) => formatCurrency(cents / 100, code, locale, copy.unknown);
  return (
    <div className="space-y-0.5 text-xs text-muted-foreground" data-testid="other-currency-lines">
      {items.map((item) => {
        const parts =
          kind === "cash"
            ? [
                item.cash_in_cents ? copy.inOf.replace("{amount}", money(item.cash_in_cents, item.currency)) : null,
                item.cash_out_cents ? copy.outOf.replace("{amount}", money(item.cash_out_cents, item.currency)) : null,
              ]
            : [
                item.revenue_cents ? copy.revenueOf.replace("{amount}", money(item.revenue_cents, item.currency)) : null,
                item.expense_cents ? copy.expenseOf.replace("{amount}", money(item.expense_cents, item.currency)) : null,
              ];
        const amounts = parts.filter(Boolean).join(", ") || shownCode(item.currency, copy.unknown);
        return (
          <p key={item.currency}>
            {copy.notConverted.replace("{amounts}", amounts).replace("{base}", base)}
            {item.assumed_rows ? ` ${copy.assumed.replace("{n}", String(item.assumed_rows))}` : ""}
          </p>
        );
      })}
      {ratios && <p>{copy.ratiosNote.replace("{base}", base)}</p>}
    </div>
  );
}

/** Where the headline currency comes from, when it is not confirmed (backend `effective_base`). */
export type BaseState = "confirmed" | "single_unconfirmed" | "ambiguous" | "no_data";

export function BaseCurrencyNotice({
  state,
  base,
  confirmPath = "/bekleyen-kayitlar",
}: {
  state: BaseState | string | null | undefined;
  base?: string | null;
  confirmPath?: string;
}) {
  const { t } = useI18n();
  const copy = t.otherCurrency;
  if (state !== "single_unconfirmed" && state !== "ambiguous") return null;
  return (
    <div className="space-y-0.5 text-xs text-amber-400" data-testid="base-currency-notice">
      {state === "ambiguous" ? (
        <>
          <p className="font-medium">{copy.chooseTitle}</p>
          <p>{copy.chooseBody}</p>
        </>
      ) : (
        <p>{copy.unconfirmed.replace("{base}", base ?? "")}</p>
      )}
      <Link href={confirmPath} className="underline underline-offset-2">
        {copy.confirmLink}
      </Link>
    </div>
  );
}

/** "12 dövizli işlem dahil değil (USD, EUR)": rows a list or total read without. */
export function LeftOutNote({ items }: { items: OtherCurrency[] | null | undefined }) {
  const { t } = useI18n();
  const n = (items ?? []).reduce((sum, i) => sum + (i.rows ?? 0), 0);
  if (!n) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid="left-out-note">
      {t.otherCurrency.leftOut
        .replace("{n}", String(n))
        .replace("{currencies}", (items ?? []).map((i) => i.currency).join(", "))}
    </p>
  );
}
