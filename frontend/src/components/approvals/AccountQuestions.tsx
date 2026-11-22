"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { useOrgSettings } from "@/hooks/useOrgSettings";
import { APPROVAL_AFFECTED_KEYS, WAITING_KEYS } from "@/hooks/useWaitingCounts";
import { answerAccountQuestion, listAccountQuestions, type AccountQuestion, type AccountSide } from "@/lib/api/accountQuestions";
import { formatCurrency } from "@/lib/utils";
import { formatDay } from "@/components/radar/basis";

/**
 * "Bu ekstreler aynı banka hesabına mı ait?": statements nothing links or separates are never added
 * together (backend app/services/bank_accounts.py). One card per pair; the owner or an admin answers,
 * everyone else sees that it waits. The answer is a recorded decision and can be changed by answering again.
 */
export function AccountQuestions() {
  const { t } = useI18n();
  const copy = t.onay;
  const { org } = useOrgSettings();
  const locale = org?.locale || "en-US";
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: WAITING_KEYS.accounts, queryFn: listAccountQuestions, retry: false });
  const answer = useMutation({
    mutationFn: ({ q, value }: { q: AccountQuestion; value: "same" | "different" }) => answerAccountQuestion(q, value),
    onSuccess: () => {
      for (const key of APPROVAL_AFFECTED_KEYS) void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  const questions = data?.questions ?? [];
  if (questions.length === 0) return null;
  const side = (s: AccountSide) =>
    `${s.name ?? "—"}${s.identity_hint ? ` (${s.identity_hint})` : ""} · ${formatDay(s.as_of, locale)} · ${formatCurrency(s.balance_cents / 100, s.currency, locale)}`;
  const title = copy.accountQuestionsTitle.replace("{n}", String(questions.length));
  return (
    <section id="hesaplar" aria-label={title} className="scroll-mt-20 space-y-2">
      <h2 className="tc-display m-0 text-[26px] leading-[1.1]">{title}</h2>
      <p className="m-0 max-w-3xl text-sm text-muted-foreground">{copy.accountQuestionsBody}</p>
      {questions.map((q) => (
        <Card key={`${q.job_ids_a.join()}|${q.job_ids_b.join()}`} className="space-y-3 p-4" data-testid="account-question">
          <p className="m-0 text-sm font-semibold">{copy.accountQuestionAsk}</p>
          <ul className="m-0 space-y-0.5 pl-4 text-sm">
            <li>{side(q.a)}</li>
            <li>{side(q.b)}</li>
          </ul>
          {data?.canDecide ? (
            <div className="flex flex-wrap gap-2">
              <Button type="button" className="min-h-[44px]" disabled={answer.isPending} onClick={() => answer.mutate({ q, value: "same" })}>
                {copy.accountQuestionSame}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="min-h-[44px]"
                disabled={answer.isPending}
                onClick={() => answer.mutate({ q, value: "different" })}
              >
                {copy.accountQuestionDifferent}
              </Button>
            </div>
          ) : (
            <p className="m-0 text-xs text-muted-foreground">{copy.accountQuestionOwnerOnly}</p>
          )}
        </Card>
      ))}
      {answer.isError && (
        <p className="m-0 text-sm text-destructive" role="alert">
          {copy.accountQuestionFailed}
        </p>
      )}
    </section>
  );
}
