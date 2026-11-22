"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { formatDay } from "@/components/radar/basis";
import { formatCurrency } from "@/lib/utils";
import type { CashRadar } from "@/lib/api/ledger";

type Copy = ReturnType<typeof useI18n>["t"]["cashRadar"];
type Fmt = (value: number) => string;

/**
 * What the starting cash is made of and what it leaves out (backend app/services/bank_accounts.py):
 * each account's latest proven balance with its own date, balances in other currencies (listed,
 * never converted), and statements whose balance could not be proven, named with the reason. Without
 * it a missing opening balance is silent about why.
 */
export function BalanceDetails({
  radar,
  copy,
  fmt,
  locale,
}: Readonly<{ radar: CashRadar; copy: Copy; fmt: Fmt; locale: string }>) {
  const opening = radar.opening_cash;
  const accounts = opening?.accounts ?? [];
  const others = radar.other_currency_balances ?? [];
  const unproven = radar.unproven_statements ?? [];
  const assumed = opening?.basis === "assumed";
  const questions = radar.account_questions ?? [];
  if (accounts.length < 2 && !assumed && others.length === 0 && unproven.length === 0 && questions.length === 0) return null;
  return (
    <Card className="space-y-3 p-4" data-testid="balance-details">
      {questions.length > 0 && (
        <div className="space-y-1" data-testid="identity-uncertain">
          {opening?.identity_note && <p className="m-0 text-sm font-semibold">{opening.identity_note}</p>}
          <p className="m-0 text-xs text-muted-foreground">{copy.identityUncertainNote}</p>
          <Link href="/onay#hesaplar" className="inline-flex min-h-[44px] items-center text-sm font-medium text-primary underline-offset-4 hover:underline">
            {copy.accountQuestionLink}
          </Link>
        </div>
      )}
      {assumed && opening?.basis_note && (
        <p className="m-0 text-sm">
          {copy.openingAssumed} {opening.basis_note}
        </p>
      )}
      {accounts.length > 1 && (
        <div className="space-y-1">
          <p className="m-0 text-sm font-semibold">{copy.accountsTitle}</p>
          <ul className="m-0 space-y-0.5 pl-4 text-sm">
            {accounts.map((a) => (
              <li key={`${a.job_id}-${a.as_of}`}>
                {a.name ?? "—"}{a.identity_hint ? ` (${a.identity_hint})` : ""} · {formatDay(a.as_of, locale)} · <span className="tabular-nums">{fmt(a.balance_cents / 100)}</span>
                {a.lagging && (
                  <span className="text-muted-foreground"> ({copy.accountBehind.replace("{days}", String(a.behind_days))})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {others.length > 0 && (
        <div className="space-y-1">
          <p className="m-0 text-sm font-semibold">{copy.otherCurrencyBalancesTitle}</p>
          <ul className="m-0 space-y-0.5 pl-4 text-sm">
            {others.map((o) => (
              <li key={o.currency}>
                <span className="tabular-nums">{formatCurrency(o.balance_cents / 100, o.currency, locale)}</span> ·{" "}
                {formatDay(o.as_of, locale)}
              </li>
            ))}
          </ul>
          <p className="m-0 text-xs text-muted-foreground">{copy.otherCurrencyBalancesNote}</p>
        </div>
      )}
      {unproven.length > 0 && (
        <div className="space-y-1">
          <p className="m-0 text-sm font-semibold">{copy.unprovenTitle}</p>
          <ul className="m-0 space-y-0.5 pl-4 text-sm">
            {unproven.map((u) => (
              <li key={u.job_id ?? u.filename}>
                {u.filename ?? "—"}: {u.reason}
              </li>
            ))}
          </ul>
          <p className="m-0 text-xs text-muted-foreground">{copy.unprovenNote}</p>
        </div>
      )}
    </Card>
  );
}
