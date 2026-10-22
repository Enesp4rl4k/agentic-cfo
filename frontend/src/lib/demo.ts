import { getSession, signIn } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * One-click guest demo entry (DEMO_PLAN D1).
 *
 * Mints an isolated demo session on the backend (POST /demo/guest) and signs
 * it in through the existing NextAuth credentials shortcut — the `access_token`
 * branch of authorize() validates it against /auth/me. No signup, no password.
 *
 * Returns true when the session is established; false on any failure
 * (demo_mode off, backend down) so callers can show an honest error state.
 *
 * `signIn(..., {redirect: false})` is not enough to prove success: next-auth
 * answers a failed CSRF check (a late duplicate /api/auth/session response can
 * overwrite the csrf cookie mid-flow) with HTTP 200 and an error-less URL, so
 * `result.error` stays null while no session cookie exists — the caller would
 * then navigate to /upload and the middleware would bounce it to the login
 * page. Re-reading the session after signIn is the protocol-agnostic check.
 */
export async function startGuestDemo(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/demo/guest`, {
      method: "POST",
    });
    if (!res.ok) return false;

    const json = await res.json().catch(() => null);
    const token: unknown = json?.data?.access_token;
    if (typeof token !== "string" || !token) return false;

    const credentials = {
      access_token: token,
      refresh_token: json?.data?.refresh_token ?? "",
      redirect: false as const,
    };

    // The csrf cookie can be clobbered by a late duplicate /api/auth/session
    // response mid-flow: the callback then answers 200 with an error-less URL
    // and no session cookie (~1 in 15 clicks under dev-server load). One
    // immediate re-attempt rides out that race — the second getCsrfToken reads
    // a settled cookie — and only an established session is ever navigated on.
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) {
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      const result = await signIn("credentials", credentials);
      if (result?.error) return false;

      const session = (await getSession().catch(() => null)) as
        | { accessToken?: unknown }
        | null;
      if (typeof session?.accessToken === "string" && session.accessToken !== "") {
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}
