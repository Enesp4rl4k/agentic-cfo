import { apiClient } from "@/lib/api/client";

// The organisation's IP allow-list (backend app/api/security.py): the owner changes it, an admin reads it.
// Every refusal below carries the server's own sentence as `Error.message` and the HTTP code as `.status`
// (lib/api/client.ts); the screen shows those sentences as given.

export interface IpAllowList {
  enabled: boolean;
  cidrs: string[];
  /** The address the server sees for the caller (owner/admin). Absent on an older server. */
  caller_ip?: string | null;
}

type Envelope<T> = { data: T; error: string | null };

export async function getIpAllowList(): Promise<IpAllowList> {
  return (await apiClient.get<Envelope<IpAllowList>>("/security/ip-whitelist")).data.data;
}

export async function saveIpAllowList(body: {
  cidrs: string[];
  enabled: boolean;
  confirmLockout?: boolean;
}): Promise<IpAllowList> {
  const res = await apiClient.put<Envelope<IpAllowList>>("/security/ip-whitelist", {
    cidrs: body.cidrs,
    enabled: body.enabled,
    confirm_lockout: body.confirmLockout ?? false,
  });
  return res.data.data;
}

/** The server's 409 for a list that would cut the caller (or others) off: it names the key to send again. */
const LOCKOUT_MARKER = "confirm_lockout";
const PREVIEW_START = "Kaydedilmedi. ";
const PREVIEW_END = " Yine de kaydetmek için";

/**
 * The lock-out preview of a 409, or null when the 409 is some other refusal (an untrusted proxy address).
 * The server's text is "Kaydedilmedi. <who would be locked out and how to recover> Yine de kaydetmek için
 * confirm_lockout=true gönderin. / Not saved. Send confirm_lockout=true ...": the middle part is returned as
 * written (who, counts and roles, the recovery sentence); the instruction to API clients is not a sentence for a person.
 */
export function lockoutPreview(error: unknown): string | null {
  const e = error as { status?: number; message?: string } | null;
  if (e?.status !== 409 || typeof e.message !== "string" || !e.message.includes(LOCKOUT_MARKER)) return null;
  const message = e.message;
  const start = message.startsWith(PREVIEW_START) ? PREVIEW_START.length : 0;
  const end = message.indexOf(PREVIEW_END);
  return (end > start ? message.slice(start, end) : message.slice(start)).trim();
}
