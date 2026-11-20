/**
 * Keeping the backend access token fresh inside the NextAuth session.
 *
 * The backend's access token lives 30 minutes; the NextAuth session 7 days. The
 * frontend never called `/auth/refresh`, so 30 minutes after signing in the next
 * request got a 401 and the user was thrown back to the login page in the
 * middle of their work, with a valid 7-day refresh token in the cookie.
 *
 * `freshToken` runs in the NextAuth `jwt` callback, which every `getSession()`
 * passes through: shortly before the access token expires it trades the refresh
 * token for a new one. If that fails the session is marked, and the API client
 * signs the user out instead of sending a token the backend will refuse.
 */
import type { JWT } from "next-auth/jwt";

/** Refresh this long before the access token actually expires. */
export const REFRESH_MARGIN_MS = 60_000;

export const REFRESH_FAILED = "RefreshAccessTokenError";

/** Milliseconds since the epoch at which a JWT expires, or null if unreadable. */
export function tokenExpiry(jwt: string | undefined): number | null {
  if (!jwt) return null;
  const part = jwt.split(".")[1];
  if (!part) return null;
  try {
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}

type Fetch = (input: string, init: RequestInit) => Promise<Pick<Response, "ok" | "json">>;

export async function freshToken(
  token: JWT,
  { apiBase, now = Date.now(), fetchImpl = fetch }: { apiBase: string; now?: number; fetchImpl?: Fetch },
): Promise<JWT> {
  const expiresAt = tokenExpiry(token.accessToken);
  // Unknown expiry: leave it to the backend's 401, as before.
  if (expiresAt === null || now < expiresAt - REFRESH_MARGIN_MS) return token;
  if (!token.refreshToken) return { ...token, error: REFRESH_FAILED };

  try {
    const res = await fetchImpl(`${apiBase}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token.refreshToken }),
    });
    if (!res.ok) return { ...token, error: REFRESH_FAILED };
    const json = (await res.json()) as { data?: { access_token?: string } };
    const access = json?.data?.access_token;
    if (!access) return { ...token, error: REFRESH_FAILED };
    return { ...token, accessToken: access, error: undefined };
  } catch {
    return { ...token, error: REFRESH_FAILED };
  }
}
