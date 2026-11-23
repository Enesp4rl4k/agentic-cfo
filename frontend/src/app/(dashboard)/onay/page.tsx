"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHead } from "@/components/brand-app/PageHead";
import { OodaFooter } from "@/components/brand-app/OodaFooter";
import Link from "next/link";
import { AccountQuestions } from "@/components/approvals/AccountQuestions";
import { DecisionHistoryToggle } from "@/components/decisions/DecisionHistoryToggle";
import { HeldAnalysesSection } from "@/components/held-analyses/HeldAnalysesSection";
import { WaitingSummary } from "@/components/approvals/WaitingSummary";
import { ReviewQueueCard } from "@/components/command-center/ReviewQueueCard";
import { useWaitingCounts } from "@/hooks/useWaitingCounts";
import { OneTapQueue, type OneTapDecision } from "@/components/approvals/OneTapQueue";
import { useCurrencyFormat } from "@/hooks/useCurrencyFormat";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import {
  getPossibleDuplicates,
  getProposedSettlements,
  resolveDuplicate,
  resolveSettlement,
  type LedgerRow,
  type ProposedSettlement,
} from "@/lib/api/ledger";
import { decidePlanChange, listPlanChanges, withdrawPlanChange } from "@/lib/api/planChanges";

const SETTLEMENTS_KEY = ["ledger-settlements"];
const DUPLICATES_KEY = ["ledger-duplicates"];
const SUMMARY_KEY = ["ledger-summary"];
const RADAR_KEY = ["cash-radar"];
const PLAN_KEY = ["plan-changes", "pending"];

const day = (iso: string) => iso.slice(0, 10);

/**
 * Pending approvals: what the system would not decide alone. A bank movement that may close an
 * invoice, and a record that looks like one already uploaded. Both are the ledger's own proposals
 * (the same ones the Command Center summarises); nothing here is invented, and nothing enters the
 * route until the person chooses.
 */
export default function OnayPage() {
  const { t } = useI18n();
  const copy = t.onay;
  const ledger = t.ledger;
  const fmt = useCurrencyFormat();
  const { profileDefaults } = useOrgSettings();
  const queryClient = useQueryClient();
  const [actionFailed, setActionFailed] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const { data: session } = useSession();
  const me = session?.user?.id ?? null;
  // `?tek=1` opens the one-tap queue straight away: the link a notification or an e-mail carries.
  const searchParams = useSearchParams();
  const [oneTap, setOneTap] = useState(searchParams?.get("tek") === "1");

  const settlements = useQuery({ queryKey: SETTLEMENTS_KEY, queryFn: getProposedSettlements });
  const duplicates = useQuery({ queryKey: DUPLICATES_KEY, queryFn: getPossibleDuplicates });
  const plans = useQuery({ queryKey: PLAN_KEY, queryFn: () => listPlanChanges("pending") });

  const refreshed = () => {
    setActionFailed(false);
    for (const key of [SETTLEMENTS_KEY, DUPLICATES_KEY, SUMMARY_KEY, RADAR_KEY, PLAN_KEY]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  };
  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "reject" }) => resolveSettlement(id, action),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "keep" | "exclude" }) => resolveDuplicate(id, action),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });

  const planDecision = useMutation({
    mutationFn: ({ id, action, ack }: { id: string; action: "approve" | "reject"; ack?: string }) =>
      ack ? decidePlanChange(id, action, reasons[id], ack) : decidePlanChange(id, action, reasons[id]),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });
  const planWithdraw = useMutation({
    mutationFn: (id: string) => withdrawPlanChange(id),
    onSuccess: refreshed,
    onError: () => setActionFailed(true),
  });

  const loading = settlements.isLoading || duplicates.isLoading || plans.isLoading;
  const failed = settlements.isError || duplicates.isError || plans.isError;
  const settlementRows: ProposedSettlement[] = settlements.data ?? [];
  const duplicateRows: LedgerRow[] = duplicates.data ?? [];
  const planRows = plans.data?.changes ?? [];
  const canDecide = Boolean(plans.data?.canDecide);
  // Deciding one's own proposal is one honest step (the button says proposer and approver are the same
  // person); with another owner or admin and an amount above the threshold it is not theirs to decide.
  const selfDecision = t.scale.selfDecision;
  const selfAck = plans.data?.selfDecisionAck ?? "";
  const ackOf = (change: { self_decision?: string | null }) => (change.self_decision === "acknowledge" ? selfAck : undefined);
  // Every kind of decision, not only the three lists below: held analyses, held rows and role results too.
  const counts = useWaitingCounts();
  // The lists appear together, once every kind has answered: a late kind would push a button the person
  // is about to press out from under their finger.
  const settled = !loading && !counts.loading;
  const nothing = !failed && settled && counts.total === 0;
  const waiting = counts.total;

  // The same decisions as the lists, one card each. A plan change is offered only to someone who may
  // decide it; anyone else's stays in the list where they can see it waits.
  const decisions: OneTapDecision[] = [
    ...settlementRows.map((s) => ({
      key: `s-${s.id}`,
      kind: copy.kindSettlement,
      title: `${s.row.description ?? copy.noCounterparty} → ${s.item.counterparty ?? s.item.description ?? copy.noCounterparty}`,
      amount: fmt(s.row.amount_cents / 100),
      meta: `${day(s.row.transaction_date)}${s.item.due_date ? ` · ${copy.dueOn.replace("{date}", day(s.item.due_date))}` : ""}`,
      options: [
        { label: ledger.settleYes, run: () => resolveSettlement(s.id, "confirm").then(refreshed) },
        { label: ledger.settleNo, run: () => resolveSettlement(s.id, "reject").then(refreshed) },
      ],
    })),
    ...duplicateRows.map((row) => ({
      key: `d-${row.id}`,
      kind: copy.kindDuplicate,
      title: row.description ?? copy.noCounterparty,
      amount: fmt(row.amount_cents / 100),
      meta: day(row.transaction_date),
      options: [
        { label: ledger.exclude, run: () => resolveDuplicate(row.id, "exclude").then(refreshed) },
        { label: ledger.keep, run: () => resolveDuplicate(row.id, "keep").then(refreshed) },
      ],
    })),
    ...(canDecide
      ? planRows.filter((change) => change.self_decision !== "blocked").map((change) => ({
          key: `p-${change.id}`,
          kind: copy.kindPlan,
          title: change.counterparty ?? change.description ?? copy.noCounterparty,
          amount: change.amount_cents !== null ? fmt(change.amount_cents / 100) : "",
          meta: copy.planMove.replace("{from}", change.from_date).replace("{to}", change.to_date),
          options: [
            {
              label: ackOf(change) ? selfDecision.confirmApprove : copy.planApprove,
              run: () =>
                (ackOf(change)
                  ? decidePlanChange(change.id, "approve", undefined, ackOf(change))
                  : decidePlanChange(change.id, "approve")
                ).then(refreshed),
            },
            { label: copy.planReject, run: () => decidePlanChange(change.id, "reject").then(refreshed) },
          ],
        }))
      : []),
  ];

  // A company profile may lead with the one-tap button (a default: the same button, the same lists, only first).
  const oneTapLeads = Boolean(profileDefaults?.one_tap_first);
  const oneTapButton =
    decisions.length > 0 ? (
      <Button className="min-h-[48px] w-full sm:w-auto" onClick={() => setOneTap(true)}>
        {copy.oneTapStart}
      </Button>
    ) : null;

  if (oneTap && !loading && !failed) {
    return (
      <div className="mx-auto max-w-5xl p-4 sm:p-8">
        <OneTapQueue decisions={decisions} onClose={() => setOneTap(false)} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-8">
      <PageHead
        step={2}
        title={copy.title}
        subtitle={copy.subtitle}
        aside={
          waiting > 0 ? (
            <span className="tc-mono rounded-full border border-border px-3 py-1 text-sm" aria-label={String(waiting)}>
              {waiting}
            </span>
          ) : undefined
        }
      />
      {settled && (<>
      {oneTapLeads && oneTapButton}
      <WaitingSummary counts={counts} />

      <div id="analizler" className="scroll-mt-20">
        <HeldAnalysesSection />
      </div>

      <AccountQuestions />

      {counts.rows > 0 && (
        <section id="kayitlar" aria-label={t.heldAnalysis.queues.rowsTitle.replace("{n}", String(counts.rows))} className="scroll-mt-20 space-y-2">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">
            {t.heldAnalysis.queues.rowsTitle.replace("{n}", String(counts.rows))}
          </h2>
          <p className="m-0 text-sm text-muted-foreground">{t.heldAnalysis.queues.rowsHint}</p>
          <Button asChild variant="outline" className="min-h-[44px]">
            <Link href="/bekleyen-kayitlar">{t.heldAnalysis.queues.openRows}</Link>
          </Button>
        </section>
      )}

      <div id="rol-sonuclari" className="scroll-mt-20">
        <ReviewQueueCard />
      </div>

      {failed && <p role="alert" className="text-sm text-destructive">{copy.failed}</p>}
      {actionFailed && <p role="alert" className="text-sm text-destructive">{copy.actionFailed}</p>}
      {nothing && <p className="text-sm text-muted-foreground">{copy.empty}</p>}
      {!oneTapLeads && oneTapButton}

      {settlementRows.length > 0 && (
        <section id="eslesmeler" aria-label={ledger.settlementsTitle.replace("{n}", String(settlementRows.length))} className="scroll-mt-20 space-y-3">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">
            {ledger.settlementsTitle.replace("{n}", String(settlementRows.length))}
          </h2>
          <ul className="space-y-3">
            {settlementRows.map((s) => (
              <li key={s.id}>
                <Card className="grid gap-4 p-4 sm:grid-cols-2">
                  <div className="space-y-1">
                    <p className="tc-eyebrow text-[11px] text-muted-foreground">{copy.movement}</p>
                    <p className="text-sm font-medium">{s.row.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {day(s.row.transaction_date)} · {fmt(s.row.amount_cents / 100)}
                    </p>
                  </div>
                  <div className="space-y-1 rounded-lg border border-border p-3">
                    <p className="tc-eyebrow text-[11px] text-muted-foreground">{copy.candidate}</p>
                    <p className="text-sm font-medium">{s.item.counterparty ?? s.item.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {fmt(s.item.amount_cents / 100)}
                      {s.item.due_date ? ` · ${copy.dueOn.replace("{date}", day(s.item.due_date))}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:col-span-2">
                    <Button
                      className="min-h-[44px]"
                      disabled={settle.isPending}
                      onClick={() => settle.mutate({ id: s.id, action: "confirm" })}
                    >
                      {ledger.settleYes}
                    </Button>
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={settle.isPending}
                      onClick={() => settle.mutate({ id: s.id, action: "reject" })}
                    >
                      {ledger.settleNo}
                    </Button>
                  </div>
                  <div className="sm:col-span-2">
                    <DecisionHistoryToggle targetType="open_item_match" targetId={s.id} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {duplicateRows.length > 0 && (
        <section id="mukerrer" aria-label={ledger.duplicatesTitle.replace("{n}", String(duplicateRows.length))} className="scroll-mt-20 space-y-3">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">
            {ledger.duplicatesTitle.replace("{n}", String(duplicateRows.length))}
          </h2>
          <p className="m-0 text-sm text-muted-foreground">{copy.duplicateHint}</p>
          <ul className="space-y-3">
            {duplicateRows.map((row) => (
              <li key={row.id}>
                <Card className="space-y-3 p-4">
                  <div>
                    <p className="text-sm font-medium">{row.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {day(row.transaction_date)} · {fmt(row.amount_cents / 100)}
                    </p>
                    {row.matches?.map((m) => (
                      <p key={m.id} className="mt-1 text-xs text-muted-foreground">
                        {ledger.alreadyThere.replace("{description}", m.description ?? "")}
                      </p>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: row.id, action: "keep" })}
                    >
                      {ledger.keep}
                    </Button>
                    <Button
                      variant="outline"
                      className="min-h-[44px]"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: row.id, action: "exclude" })}
                    >
                      {ledger.exclude}
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {planRows.length > 0 && (
        <section id="odeme-plani" aria-label={copy.planTitle} className="scroll-mt-20 space-y-3">
          <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{copy.planTitle}</h2>
          <p className="m-0 text-sm text-muted-foreground">{copy.planHint}</p>
          <ul className="space-y-3">
            {planRows.map((change) => (
              <li key={change.id}>
                <Card className="space-y-3 p-4">
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{change.counterparty ?? change.description ?? copy.noCounterparty}</p>
                    <p className="tc-mono text-sm text-muted-foreground">
                      {change.amount_cents !== null ? `${fmt(change.amount_cents / 100)} · ` : ""}
                      {copy.planMove.replace("{from}", change.from_date).replace("{to}", change.to_date)}
                    </p>
                    {change.request_note && (
                      <p className="m-0 text-xs text-muted-foreground">{copy.planBy.replace("{note}", change.request_note)}</p>
                    )}
                  </div>
                  {change.threshold_changed_by_proposer && (
                    <p className="m-0 text-xs font-medium text-warning">{selfDecision.thresholdMoved}</p>
                  )}
                  {canDecide && change.self_decision === "blocked" && (
                    <div className="space-y-2">
                      <p className="m-0 text-sm font-medium">{selfDecision.blockedTitle}</p>
                      {change.self_decision_message && (
                        <p className="m-0 text-xs text-muted-foreground">{change.self_decision_message}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          variant="outline"
                          className="min-h-[44px]"
                          disabled={planWithdraw.isPending}
                          onClick={() => planWithdraw.mutate(change.id)}
                        >
                          {copy.planWithdraw}
                        </Button>
                      </div>
                    </div>
                  )}
                  {canDecide && change.self_decision === "blocked" ? null : canDecide ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        aria-label={copy.planReason}
                        placeholder={copy.planReason}
                        value={reasons[change.id] ?? ""}
                        onChange={(e) => setReasons((r) => ({ ...r, [change.id]: e.target.value }))}
                        className="min-h-[44px] min-w-[200px] flex-1 rounded-md border border-border bg-card px-3 text-sm"
                      />
                      <Button
                        className="min-h-[44px]"
                        disabled={planDecision.isPending}
                        onClick={() => planDecision.mutate({ id: change.id, action: "approve", ack: ackOf(change) })}
                      >
                        {ackOf(change) ? selfDecision.confirmApprove : copy.planApprove}
                      </Button>
                      <Button
                        variant="outline"
                        className="min-h-[44px]"
                        disabled={planDecision.isPending}
                        onClick={() => planDecision.mutate({ id: change.id, action: "reject" })}
                      >
                        {copy.planReject}
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-wrap items-center gap-3">
                      <p className="m-0 text-sm text-muted-foreground">{copy.planWaiting}</p>
                      {me !== null && change.requested_by === me && (
                        <Button
                          variant="outline"
                          className="min-h-[44px]"
                          disabled={planWithdraw.isPending}
                          onClick={() => planWithdraw.mutate(change.id)}
                        >
                          {copy.planWithdraw}
                        </Button>
                      )}
                    </div>
                  )}
                  <DecisionHistoryToggle targetType="payment_plan_change" targetId={change.id} />
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      </>)}

      <OodaFooter current={2} />
    </div>
  );
}
