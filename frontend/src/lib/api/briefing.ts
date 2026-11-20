import { apiClient } from "@/lib/api/client";

// The Monday briefing (backend app/services/monday_briefing.py): three sentences
// written from the cash radar's facts. The page shows them as written and computes
// nothing. Amounts are kuruş.

export interface MondayBriefing {
  briefing_id: string;
  org_id: string;
  week_start: string;
  week_end: string;
  starting_cash_cents: number | null;
  net_change_cents: number;
  end_balance_cents: number;
  approaching_title: string;
  approaching_amount_cents: number;
  approaching_date: string | null;
  action_type: string;
  action_title: string;
  action_detail: string;
  action_amount_cents: number;
  sentence_radar: string;
  sentence_obligation: string;
  sentence_action: string;
  full_text: string;
  /** The shown text always passed the number check; false would mean it did not. */
  verified: boolean;
  /** True when a model's wording was rejected and the fixed template was used instead. */
  fallback_used: boolean;
  balance_known: boolean;
  /** False when nothing is known about the company: there is no briefing to read. */
  has_data: boolean;
}

/** What the owner can answer; the words are the server's own. */
export type BriefingResponse = "done" | "deferred" | "dismissed";

export interface BriefingAnswer {
  decision_id: string;
  status: string;
  chosen_option_label: string;
  briefing_id: string;
}

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getMondayBriefing(): Promise<MondayBriefing> {
  const res = await apiClient.get<Envelope<MondayBriefing>>("/briefing/monday");
  return res.data.data;
}

/** The answer belongs to the briefing of the week it names; answering again replaces it. */
export async function respondToMondayBriefing(
  response: BriefingResponse,
  anchorDate: string,
): Promise<BriefingAnswer> {
  const res = await apiClient.post<Envelope<BriefingAnswer>>("/briefing/monday/respond", {
    response,
    anchor_date: anchorDate,
  });
  return res.data.data;
}
