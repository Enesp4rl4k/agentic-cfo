/**
 * Re-reading who the backend says you are, inside the NextAuth session.
 *
 * The session's `role` and `orgId` were copied from the backend once, at sign-in.
 * Registering signs in *before* the workspace exists (an analyst, no organisation)
 * and the backend then makes the user its owner; switching organisation changes the
 * role again (an accountant is `smmm` in a client). The cookie kept the old role
 * until the next login, so the middleware sent a new owner away from
 * /settings/workspace and an accountant into a client with the home role.
 *
 * `useSession().update()` runs the `jwt` callback with `trigger === "update"`;
 * this is what it does there.
 */
import type { JWT } from "next-auth/jwt";

type Fetch = (input: string, init: RequestInit) => Promise<Pick<Response, "ok" | "json">>;

export async function syncIdentity(
  token: JWT,
  { apiBase, fetchImpl = fetch }: { apiBase: string; fetchImpl?: Fetch },
): Promise<JWT> {
  if (!token.accessToken) return token;
  try {
    const res = await fetchImpl(`${apiBase}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token.accessToken}` },
    });
    if (!res.ok) return token;
    const me = ((await res.json()) as { data?: { role?: string; org_id?: string | null } })?.data;
    if (!me?.role) return token;
    return { ...token, role: me.role, orgId: me.org_id ?? null };
  } catch {
    return token;
  }
}
