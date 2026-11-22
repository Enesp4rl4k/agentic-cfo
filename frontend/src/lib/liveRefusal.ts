import { apiClient } from "@/lib/api/client";

/**
 * Why a live connection (chat, alerts) was refused.
 *
 * The server closes a WebSocket with code 1008 ("policy violation") when the person may no longer act in the
 * company: the company's IP allow-list does not contain their address, or their membership was removed or
 * moved. The close frame carries no reason text, and a refusal before the handshake completes reaches the
 * browser as an abnormal close (1006) with no code at all. What the server offers instead is the same refusal
 * on a plain request: every organisation-scoped call from an address outside the list answers 403 with the
 * sentence that says what happened and how to recover (`ip_allowlist.refusal_text`, tr + en). One such read
 * is asked after a close, so the screen can show that sentence as written.
 */
export const POLICY_CLOSE = 1008;

export interface LiveRefusal {
  /** The server's own 403 sentence, once it has answered; null until then (and when it gave none). */
  sentence: string | null;
}

/** The server's refusal sentence for this caller, or null when a plain request is not refused (then it was not a refusal). */
export async function explainRefusal(): Promise<string | null> {
  try {
    await apiClient.get("/org/me");
    return null;
  } catch (e) {
    const err = e as { status?: number; message?: string } | null;
    return err?.status === 403 && err.message ? err.message : null;
  }
}
