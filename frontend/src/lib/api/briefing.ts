import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/pilot-schema";

// The Monday briefing (backend app/services/monday_briefing.py): three sentences
// written from the cash radar's facts. The page shows them as written and computes
// nothing. Amounts are kuruş.

/** Generated from the backend's schema; see pilot-schema.ts. */
export type MondayBriefing = components["schemas"]["MondayBriefing"];

/** What the owner can answer; the words are the server's own. */
export type BriefingResponse = "done" | "deferred" | "dismissed";

export type BriefingAnswer = components["schemas"]["BriefingAnswer"];

interface Envelope<T> {
  data: T;
  error: string | null;
}

export async function getMondayBriefing(): Promise<MondayBriefing> {
  const res = await apiClient.get<Envelope<MondayBriefing>>("/briefing/monday");
  return res.data.data;
}

/**
 * The answer belongs to the briefing the owner read: its week and its fingerprint.
 * Answering again replaces it. If the figures changed since it was loaded the server
 * refuses with 409, and the page reloads the briefing instead of saving.
 */
export async function respondToMondayBriefing(
  response: BriefingResponse,
  anchorDate: string,
  fingerprint: string,
): Promise<BriefingAnswer> {
  const res = await apiClient.post<Envelope<BriefingAnswer>>("/briefing/monday/respond", {
    response,
    anchor_date: anchorDate,
    fingerprint,
  });
  return res.data.data;
}
