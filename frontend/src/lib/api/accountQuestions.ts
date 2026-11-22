import { apiClient } from "@/lib/api/client";

// Account questions (backend app/services/bank_accounts.py, routes in app/api/held_rows.py). Kept apart
// from heldRows.ts so the held-rows screens and their tests do not depend on it.

interface Envelope<T> {
  data: T;
  error: string | null;
}

/** One side of an account question: the newest proven balance of a group of statements. */
export interface AccountSide {
  name: string | null;
  as_of: string;
  balance_cents: number;
  currency: string;
}

/** Two proven statements nothing links or separates: are they one bank account? */
export interface AccountQuestion {
  question: string;
  a: AccountSide;
  b: AccountSide;
  job_ids_a: string[];
  job_ids_b: string[];
}

export async function listAccountQuestions(): Promise<{ questions: AccountQuestion[]; canDecide: boolean }> {
  const res = await apiClient.get<Envelope<{ questions: AccountQuestion[]; can_decide: boolean }>>("/held-rows/account-questions");
  return { questions: res.data.data.questions, canDecide: res.data.data.can_decide };
}

/** Owner or admin only. Recorded as a decision; answering again changes the answer. */
export async function answerAccountQuestion(q: AccountQuestion, answer: "same" | "different"): Promise<void> {
  await apiClient.post("/held-rows/account-questions/answer", { answer, job_ids_a: q.job_ids_a, job_ids_b: q.job_ids_b });
}

