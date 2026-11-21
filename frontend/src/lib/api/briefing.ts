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

// The two delivery routes have no response model in the backend's OpenAPI schema (app/api/
// monday_briefing.py returns plain dicts), so they are absent from pilot-schema.ts and their shape is
// written here, from outbox.py / briefing_delivery.deliveries. Give them a response_model and
// `npm run gen:api` replaces these.

/** One e-mail of the briefing: `status` is the outbox's own (held, pending, sent, failed). */
export interface BriefingDelivery {
  recipient: string;
  status: string;
  reason: string | null;
  attempts: number;
  sent_at: string | null;
}

export async function getBriefingDeliveries(briefingId: string): Promise<BriefingDelivery[]> {
  const res = await apiClient.get<Envelope<BriefingDelivery[]>>("/briefing/monday/deliveries", {
    params: { briefing_id: briefingId },
  });
  return res.data.data;
}

export interface BriefingChange {
  field: string;
  label: string;
  old: string;
  new: string;
}

export interface BriefingReleaseResult {
  released: number;
  /** The figures moved since the e-mail was written: nothing was sent, `changes` says what changed. */
  needs_confirmation?: boolean;
  changes?: BriefingChange[];
  fingerprint?: string;
  refreshed?: boolean;
}

/**
 * Only the company's accountant may; anyone else gets 403. When the figures changed since the
 * e-mail was written nothing is sent: send the returned `fingerprint` back as `confirmFingerprint`
 * to send the refreshed text.
 */
export async function releaseMondayBriefing(
  briefingId: string,
  confirmFingerprint?: string,
): Promise<BriefingReleaseResult> {
  const res = await apiClient.post<Envelope<BriefingReleaseResult>>("/briefing/monday/release", {
    briefing_id: briefingId,
    ...(confirmFingerprint ? { confirm_fingerprint: confirmFingerprint } : {}),
  });
  return res.data.data;
}
